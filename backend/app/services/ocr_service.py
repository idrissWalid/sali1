"""
ocr_service.py — OCR local de PDF scannés via RapidOCR (ONNX, CPU).

Objectif : rendre un document scanné exploitable SANS LLM multimodal. Le texte
reconnu est réinjecté dans le pipeline documentaire habituel (indexation
ChromaDB + résumé), ce qui permet d'utiliser n'importe quel modèle texte —
y compris un modèle Ollama local — là où le fallback visuel (ColSmolVLM +
Gemini Vision) imposait obligatoirement Gemini.

En bonus, les positions des boîtes OCR permettent de reconstruire un tableau
en DataFrame, afin qu'un tableau scanné puisse lui aussi devenir un dataset.
"""

import io
import statistics

import pandas as pd

# Au-delà, l'OCR CPU devient trop lent pour une requête d'upload synchrone.
MAX_OCR_PAGES = 30
OCR_DPI = 200
MIN_CONFIDENCE = 0.5

_engine = None


def _get_engine():
    """Charge le moteur RapidOCR une seule fois (modèles ONNX ~15 Mo)."""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _render_pages(file_bytes: bytes, dpi: int = OCR_DPI, max_pages: int = MAX_OCR_PAGES):
    """Rasterise les pages du PDF en tableaux numpy (via PyMuPDF, déjà utilisé
    ailleurs dans le projet pour le fallback visuel)."""
    import fitz
    import numpy as np
    from PIL import Image

    images = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    for page in list(doc)[:max_pages]:
        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        images.append(np.array(img))
    doc.close()
    return images


def ocr_pdf_pages(file_bytes: bytes, dpi: int = OCR_DPI, max_pages: int = MAX_OCR_PAGES) -> list[dict]:
    """OCR page par page.

    Retourne [{"page": int, "text": str, "items": [{"x", "y", "h", "text"}]}].
    Les `items` conservent la géométrie, nécessaire pour reconstruire un tableau.
    """
    engine = _get_engine()
    pages = []

    for page_index, image in enumerate(_render_pages(file_bytes, dpi, max_pages), start=1):
        try:
            result, _ = engine(image)
        except Exception:
            continue

        items = []
        for entry in result or []:
            try:
                box, text, confidence = entry[0], entry[1], entry[2]
            except (IndexError, TypeError, ValueError):
                continue
            if not text or not str(text).strip() or confidence < MIN_CONFIDENCE:
                continue

            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            items.append({
                "x": min(xs),
                "y": sum(ys) / len(ys),
                "h": max(ys) - min(ys),
                "text": str(text).strip(),
            })

        items.sort(key=lambda item: (item["y"], item["x"]))
        pages.append({
            "page": page_index,
            "text": " ".join(item["text"] for item in items),
            "items": items,
        })

    return pages


def ocr_pdf(file_bytes: bytes, dpi: int = OCR_DPI, max_pages: int = MAX_OCR_PAGES) -> str:
    """Texte complet reconnu dans le PDF scanné (chaîne vide si rien de lisible)."""
    pages = ocr_pdf_pages(file_bytes, dpi, max_pages)
    return "\n\n".join(page["text"] for page in pages if page["text"].strip()).strip()


def _group_items_into_rows(items: list[dict]) -> list[list[dict]]:
    """Regroupe les boîtes OCR en lignes visuelles selon leur ordonnée."""
    if not items:
        return []

    heights = [item["h"] for item in items if item["h"] > 0]
    tolerance = (statistics.median(heights) * 0.6) if heights else 10

    rows = []
    current_row = [items[0]]
    for item in items[1:]:
        if abs(item["y"] - current_row[-1]["y"]) <= tolerance:
            current_row.append(item)
        else:
            rows.append(sorted(current_row, key=lambda i: i["x"]))
            current_row = [item]
    rows.append(sorted(current_row, key=lambda i: i["x"]))
    return rows


def _rows_to_cells(rows: list[list[dict]]) -> list[list[str]]:
    """Convertit les lignes de boîtes en listes de cellules.

    Deux cas se présentent selon le rendu du scan : soit l'OCR isole chaque
    cellule (une boîte par cellule), soit il fusionne toute la ligne en une
    seule boîte — auquel cas on retombe sur un découpage aux espaces multiples.
    """
    cells_per_row = []
    for row in rows:
        if len(row) > 1:
            cells_per_row.append([item["text"] for item in row])
        else:
            parts = [part for part in row[0]["text"].split("  ") if part.strip()]
            cells_per_row.append([part.strip() for part in parts])
    return cells_per_row


def extract_table_from_ocr(pages: list[dict], min_rows: int = 3, min_cols: int = 2):
    """Tente de reconstruire un tableau à partir des boîtes OCR.

    Retourne un DataFrame, ou None si aucune structure tabulaire crédible n'est
    trouvée. L'heuristique retient la largeur de colonne la plus fréquente et ne
    conserve que les lignes qui la respectent, afin d'écarter titres et
    paragraphes qui entourent le tableau.
    """
    all_cells = []
    for page in pages:
        rows = _group_items_into_rows(page.get("items", []))
        all_cells.extend(_rows_to_cells(rows))

    candidate_rows = [row for row in all_cells if len(row) >= min_cols]
    if len(candidate_rows) < min_rows:
        return None

    widths = [len(row) for row in candidate_rows]
    dominant_width = statistics.mode(widths)
    if dominant_width < min_cols:
        return None

    table_rows = [row for row in candidate_rows if len(row) == dominant_width]
    if len(table_rows) < min_rows:
        return None

    header = table_rows[0]
    body = table_rows[1:]
    if not body:
        return None

    # Noms de colonnes uniques et non vides
    seen = {}
    columns = []
    for index, name in enumerate(header):
        clean = (name or "").strip() or f"col_{index + 1}"
        count = seen.get(clean, 0)
        columns.append(clean if count == 0 else f"{clean}_{count}")
        seen[clean] = count + 1

    df = pd.DataFrame(body, columns=columns)

    # L'OCR ne renvoie que du texte : on retente une conversion numérique par
    # colonne (virgule décimale et séparateurs de milliers tolérés).
    for column in df.columns:
        as_text = (
            df[column].astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        converted = pd.to_numeric(as_text, errors="coerce")
        if len(df) > 0 and converted.notna().sum() / len(df) >= 0.9:
            df[column] = converted

    return df


def extract_table_from_scanned_pdf(file_bytes: bytes):
    """Raccourci : OCR du PDF puis reconstruction du tableau, ou None."""
    return extract_table_from_ocr(ocr_pdf_pages(file_bytes))
