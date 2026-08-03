"""
ocr_service.py — Lecture des PDF scannés, par cascade de trois moteurs.

Objectif : rendre un document scanné exploitable comme un document texte
ordinaire. Le texte reconnu réintègre le pipeline documentaire habituel
(indexation ChromaDB, résumé, citations), ce qui garde le document lisible par
N'IMPORTE QUEL modèle texte — y compris un Ollama local — une fois la
transcription faite.

Trois moteurs sont tentés dans l'ordre, le premier qui rend du texte gagne :

1. **Unlimited-OCR** — un serveur externe (vLLM/SGLang) joint par son API
   OpenAI-compatible. Le meilleur résultat, mais il exige un GPU CUDA sur la
   machine qui l'héberge. Voir « README ocr.md ».
2. **Le modèle vision de l'utilisateur** — les pages sont envoyées au modèle
   multimodal déjà sélectionné (Gemini, GPT-4o, Claude, llava…) avec pour seule
   consigne de TRANSCRIRE. Ne demande aucun serveur, mais consomme des appels
   d'API et suppose un modèle multimodal.
3. **RapidOCR** — moteur ONNX local, sur CPU, sans dépendance système ni
   réseau. Qualité inférieure, en particulier sur les tableaux (voir
   `_table_depuis_geometrie`), mais c'est le seul recours qui fonctionne hors
   ligne, sans GPU et sans clé d'API.

Chaque moteur rend la même forme — `[{"page": int, "text": str}]` — de sorte que
la suite du pipeline ignore lequel a servi. RapidOCR ajoute une clé `items`
(géométrie des boîtes), seule façon de reconstruire un tableau quand le moteur
ne rend pas de markdown.
"""

import base64
import logging
import os
import re
import statistics
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

logger = logging.getLogger("app.ocr")

# Au-delà, une requête d'upload synchrone attend trop longtemps — et sur le
# moteur 2 chaque page est un appel d'API facturé.
MAX_OCR_PAGES = 30


# ══════════════════════════════════════════════════════════════════════════════
# Rendu des pages (commun aux trois moteurs)
# ══════════════════════════════════════════════════════════════════════════════

def _render_pages(file_bytes: bytes, dpi: int, max_pages: int = MAX_OCR_PAGES) -> list[bytes]:
    """Rasterise les pages du PDF en PNG (via PyMuPDF)."""
    import fitz

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    images = [page.get_pixmap(matrix=matrix).tobytes("png") for page in list(doc)[:max_pages]]
    doc.close()
    return images


# ══════════════════════════════════════════════════════════════════════════════
# Moteur 1 — Unlimited-OCR (serveur externe, OpenAI-compatible)
# ══════════════════════════════════════════════════════════════════════════════

# Même convention que OLLAMA_API_URL : l'URL complète du point d'entrée, pour
# qu'un serveur derrière un proxy ou sur un autre chemin reste joignable sans
# toucher au code. Port 10000 = celui du serveur décrit dans « README ocr.md ».
OCR_API_URL = os.getenv("OCR_API_URL", "http://localhost:10000/v1/chat/completions")
OCR_MODEL = os.getenv("OCR_MODEL", "Unlimited-OCR")
OCR_TIMEOUT = int(os.getenv("OCR_TIMEOUT", "1200"))

# 300 dpi : la valeur retenue par le `pdf_to_images` de référence du modèle.
UNLIMITED_DPI = 300
# Le serveur traite plusieurs pages de front ; 8 est la concurrence par défaut
# de l'`infer.py` de référence.
UNLIMITED_CONCURRENCY = 8
# Configuration d'image documentée pour une page seule : « gundam » découpe la
# page en tuiles et lit les petits caractères que le mode « base » manque.
UNLIMITED_IMAGE_MODE = "gundam"
UNLIMITED_PROMPT = "document parsing."

# Garde anti-répétition du modèle. SGLang l'attend sous forme d'une classe
# sérialisée (`DeepseekOCRNoRepeatNGramLogitProcessor.to_str()`), qui n'est
# obtenable qu'en important le paquet `sglang` — hors de question ici, tout
# l'intérêt du chemin HTTP étant de ne rien installer côté backend. La chaîne est
# donc lue dans l'environnement : renseignée, la garde est active ; absente, le
# serveur applique ses propres réglages. vLLM n'en a pas besoin, sa recette la
# câblant côté serveur.
OCR_LOGIT_PROCESSOR = os.getenv("OCR_LOGIT_PROCESSOR", "").strip()
OCR_NGRAM_SIZE = 35
OCR_NGRAM_WINDOW = 128

# Marqueurs de localisation « <|det|>type [bbox]<|/det|> » que le modèle insère
# devant chaque bloc reconnu. Utiles pour évaluer une détection de mise en page,
# inutiles pour du texte à indexer : on les retire. `skip_special_tokens` est
# laissé à False dans la requête précisément pour qu'ils arrivent entiers et
# soient retirables d'un bloc — filtrés côté serveur, il n'en resterait que les
# coordonnées nues, au milieu du texte.
_DET_RE = re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL)


def _strip_det(raw: str) -> str:
    """Texte reconnu débarrassé des marqueurs de localisation."""
    lignes = [ligne.rstrip() for ligne in _DET_RE.sub("", raw or "").splitlines()]
    return "\n".join(ligne for ligne in lignes if ligne.strip()).strip()


def _unlimited_une_page(session: requests.Session, png_bytes: bytes) -> str:
    """Envoie une page au serveur Unlimited-OCR et renvoie le markdown reconnu."""
    encoded = base64.b64encode(png_bytes).decode("ascii")
    payload = {
        "model": OCR_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": UNLIMITED_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ],
        }],
        # Déterminisme : deux uploads du même scan doivent donner le même texte,
        # sans quoi l'indexation et le résumé varieraient d'une fois sur l'autre.
        "temperature": 0,
        "skip_special_tokens": False,
        "images_config": {"image_mode": UNLIMITED_IMAGE_MODE},
    }
    if OCR_LOGIT_PROCESSOR:
        payload["custom_logit_processor"] = OCR_LOGIT_PROCESSOR
        payload["custom_params"] = {
            "ngram_size": OCR_NGRAM_SIZE,
            "window_size": OCR_NGRAM_WINDOW,
        }

    response = session.post(OCR_API_URL, json=payload, timeout=OCR_TIMEOUT)
    response.raise_for_status()
    message = response.json()["choices"][0].get("message") or {}
    return _strip_det(message.get("content") or "")


def _ocr_unlimited(file_bytes: bytes, max_pages: int) -> list[dict]:
    """Moteur 1. Liste vide si le serveur est injoignable.

    Une requête par page plutôt qu'un seul appel multi-pages : le format de
    sortie groupé ne documente aucun séparateur de page, et le deviner ferait
    reposer la numérotation — donc les citations RAG — sur une heuristique. Le
    mode « gundam », réservé à l'image seule, lit en outre mieux les petits
    caractères que le mode « base » imposé au multi-pages.
    """
    images = _render_pages(file_bytes, UNLIMITED_DPI, max_pages)
    if not images:
        return []

    def tenter(session, image):
        try:
            return _unlimited_une_page(session, image)
        except Exception as error:
            logger.warning("Unlimited-OCR (%s) : page ignorée — %s", OCR_API_URL, error)
            return ""

    with requests.Session() as session:
        # `trust_env=False` : un proxy d'entreprise hérité de l'environnement
        # détournerait l'appel vers un serveur d'inférence local.
        session.trust_env = False
        with ThreadPoolExecutor(max_workers=min(UNLIMITED_CONCURRENCY, len(images))) as pool:
            textes = list(pool.map(lambda img: tenter(session, img), images))

    return [{"page": i, "text": t} for i, t in enumerate(textes, start=1) if t]


# ══════════════════════════════════════════════════════════════════════════════
# Moteur 2 — transcription par le modèle vision de l'utilisateur
# ══════════════════════════════════════════════════════════════════════════════

# 200 dpi : au-delà, le poids de l'image grossit plus vite que la qualité de
# lecture, et chaque page est ici un appel d'API facturé au volume.
VISION_DPI = 200
# Prudent : les API multimodales appliquent des quotas par minute, et dépasser
# se paie en 429 sur un upload que l'utilisateur attend.
VISION_CONCURRENCY = 4

# Prompt système dédié : sans lui, `ask_vision` pose celui de l'agent d'analyse,
# qui impose de conclure par des suggestions d'analyses complémentaires. La
# transcription reviendrait enrobée de commentaires.
_VISION_SYSTEM = (
    "Tu es un moteur de transcription de documents. Tu ne réponds jamais à une "
    "question, tu ne commentes jamais, tu n'ajoutes ni introduction ni "
    "conclusion : tu restitues le contenu de l'image, et rien d'autre."
)

_VISION_PROMPT = """Transcris intégralement le contenu de cette page en markdown.

Règles :
- Restitue le texte MOT À MOT, dans la langue d'origine du document. Ne traduis
  pas, ne résume pas, ne reformule pas, ne corrige pas les fautes.
- Rends les tableaux sous forme de tableaux markdown (`| colonne | colonne |`),
  avec leur ligne de séparation.
- Rends les titres avec des `#`, les listes avec des `-`.
- Ignore les éléments purement décoratifs (filigranes, logos, bordures).
- Si la page est vide ou totalement illisible, réponds exactement : (page vide)

N'écris rien d'autre que la transcription."""

# Réponse convenue pour une page vide : à filtrer, sinon elle serait indexée
# comme du contenu.
_VISION_PAGE_VIDE = "(page vide)"


def _ocr_vision(file_bytes: bytes, max_pages: int, model: str | None) -> list[dict]:
    """Moteur 2. Liste vide si le modèle n'est pas multimodal ou si tout échoue."""
    from app.services.vision_service import VisionNonSupportee, ask_vision, supporte_vision

    if not supporte_vision(model):
        logger.info("Transcription vision ignorée : %s n'est pas multimodal.",
                    model or "modèle par défaut")
        return []

    images = _render_pages(file_bytes, VISION_DPI, max_pages)
    if not images:
        return []

    def tenter(png_bytes: bytes) -> str:
        try:
            texte = ask_vision(_VISION_PROMPT, [png_bytes], model=model,
                               system=_VISION_SYSTEM)
        except VisionNonSupportee:
            return ""
        except Exception as error:
            logger.warning("Transcription vision (%s) : page ignorée — %s", model, error)
            return ""
        texte = (texte or "").strip()
        return "" if texte.lower().startswith(_VISION_PAGE_VIDE) else texte

    with ThreadPoolExecutor(max_workers=min(VISION_CONCURRENCY, len(images))) as pool:
        textes = list(pool.map(tenter, images))

    return [{"page": i, "text": t} for i, t in enumerate(textes, start=1) if t]


# ══════════════════════════════════════════════════════════════════════════════
# Moteur 3 — RapidOCR (ONNX, CPU, hors ligne)
# ══════════════════════════════════════════════════════════════════════════════

RAPIDOCR_DPI = 200
RAPIDOCR_MIN_CONFIDENCE = 0.5

_engine = None


def _get_engine():
    """Charge le moteur RapidOCR une seule fois (modèles ONNX ~15 Mo)."""
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


def _ocr_rapidocr(file_bytes: bytes, max_pages: int) -> list[dict]:
    """Moteur 3. Conserve la géométrie des boîtes dans `items`, nécessaire pour
    reconstruire un tableau — RapidOCR ne rend que du texte plat."""
    import numpy as np
    from PIL import Image
    import io

    try:
        engine = _get_engine()
    except Exception as error:
        logger.warning("RapidOCR indisponible : %s", error)
        return []

    pages = []
    for page_index, png_bytes in enumerate(_render_pages(file_bytes, RAPIDOCR_DPI, max_pages), start=1):
        try:
            image = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
            result, _ = engine(image)
        except Exception as error:
            logger.warning("RapidOCR : page %d ignorée — %s", page_index, error)
            continue

        items = []
        for entry in result or []:
            try:
                box, text, confidence = entry[0], entry[1], entry[2]
            except (IndexError, TypeError, ValueError):
                continue
            if not text or not str(text).strip() or confidence < RAPIDOCR_MIN_CONFIDENCE:
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
        texte = " ".join(item["text"] for item in items)
        if texte.strip():
            pages.append({"page": page_index, "text": texte, "items": items})

    return pages


# ══════════════════════════════════════════════════════════════════════════════
# Cascade
# ══════════════════════════════════════════════════════════════════════════════

def ocr_pdf_pages(file_bytes: bytes, max_pages: int = MAX_OCR_PAGES,
                  model: str | None = None) -> list[dict]:
    """Texte du PDF scanné, par le premier moteur qui rend quelque chose.

    Retourne `[{"page": int, "text": str}]` — plus une clé `items` si c'est
    RapidOCR qui a servi. Liste vide si les trois moteurs échouent.

    Les moteurs ne sont pas départagés sur la qualité mais sur la disponibilité :
    chacun est plus exigeant que le suivant (un GPU, puis un modèle multimodal,
    puis rien), et l'ordre va donc du meilleur résultat au plus robuste.
    """
    moteurs = (
        ("Unlimited-OCR", lambda: _ocr_unlimited(file_bytes, max_pages)),
        ("transcription vision", lambda: _ocr_vision(file_bytes, max_pages, model)),
        ("RapidOCR", lambda: _ocr_rapidocr(file_bytes, max_pages)),
    )

    for nom, moteur in moteurs:
        try:
            pages = moteur()
        except Exception as error:
            # Un moteur qui casse ne doit jamais empêcher d'essayer le suivant.
            logger.warning("Moteur OCR « %s » en échec — %s", nom, error)
            continue
        if pages:
            logger.info("OCR : %d page(s) lue(s) par « %s ».", len(pages), nom)
            return pages
        logger.info("OCR : « %s » n'a rien rendu, passage au moteur suivant.", nom)

    logger.warning("OCR : les trois moteurs ont échoué, aucun texte extrait.")
    return []


def ocr_pdf(file_bytes: bytes, max_pages: int = MAX_OCR_PAGES,
            model: str | None = None) -> str:
    """Texte complet reconnu dans le PDF scanné (chaîne vide si rien de lisible)."""
    pages = ocr_pdf_pages(file_bytes, max_pages, model)
    return "\n\n".join(page["text"] for page in pages if page["text"].strip()).strip()


# ══════════════════════════════════════════════════════════════════════════════
# Reconstruction d'un tableau
# ══════════════════════════════════════════════════════════════════════════════

# Ligne de séparation d'une table markdown (« |---|:---:| »), seul marqueur
# fiable pour distinguer une vraie table d'un paragraphe contenant des « | ».
_SEPARATEUR_MD_RE = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$")


def _cellules(ligne: str) -> list[str]:
    """Cellules d'une ligne de table markdown, bordures extérieures retirées."""
    ligne = ligne.strip()
    if ligne.startswith("|"):
        ligne = ligne[1:]
    if ligne.endswith("|"):
        ligne = ligne[:-1]
    return [cellule.strip() for cellule in ligne.split("|")]


def _tables_markdown(texte: str) -> list[list[list[str]]]:
    """Toutes les tables markdown d'un texte, en-tête en première ligne.

    Une table est reconnue à sa ligne de séparation : sans elle, une simple
    phrase contenant des « | » passerait pour un tableau.
    """
    lignes = texte.splitlines()
    tables = []
    index = 0
    while index < len(lignes):
        est_entete = (
            "|" in lignes[index]
            and index + 1 < len(lignes)
            and _SEPARATEUR_MD_RE.match(lignes[index + 1])
        )
        if not est_entete:
            index += 1
            continue

        table = [_cellules(lignes[index])]
        index += 2
        while index < len(lignes) and "|" in lignes[index]:
            table.append(_cellules(lignes[index]))
            index += 1
        tables.append(table)

    return tables


def _signature(ligne: list[str]) -> tuple:
    """Forme comparable d'une ligne, pour reconnaître un en-tête répété."""
    return tuple(str(cellule).strip().lower() for cellule in ligne)


def _table_depuis_markdown(pages: list[dict], min_rows: int, min_cols: int):
    """Recolle les tables markdown d'un tableau étalé sur plusieurs pages.

    La transcription se fait page par page : un tableau de 8 pages ressort en 8
    tables markdown distinctes. Les recoller est indispensable — sans ça, seule
    une page était retenue et 7/8 des lignes disparaissaient silencieusement du
    dashboard.

    Deux formes de continuation coexistent selon le document et le moteur :
    l'en-tête est répété sur chaque page (il faut alors le sauter), ou il ne
    figure que sur la première (la première ligne des pages suivantes est alors
    une donnée, à conserver).
    """
    morceaux = [
        (page.get("page", index), table)
        for index, page in enumerate(pages, start=1)
        for table in _tables_markdown(page.get("text", ""))
        if len(table) >= 2 and len(table[0]) >= min_cols
    ]
    if not morceaux:
        return None

    # Regroupement par nombre de colonnes : c'est ce qui sépare le tableau de
    # données d'un encart de mise en page voisin (en-tête de rapport, légende).
    groupes: dict[int, list] = {}
    for numero, table in morceaux:
        groupes.setdefault(len(table[0]), []).append((numero, table))

    # Le groupe qui porte le plus de lignes est le tableau de données.
    largeur = max(groupes, key=lambda cle: sum(len(t) for _, t in groupes[cle]))
    # Ordre des pages : la première porte l'en-tête de référence.
    ordonnes = sorted(groupes[largeur], key=lambda item: item[0])

    entete = ordonnes[0][1][0]
    signature = _signature(entete)
    corps = []
    for _, table in ordonnes:
        debut = 1 if _signature(table[0]) == signature else 0
        corps.extend(table[debut:])

    if len(corps) + 1 < min_rows:
        return None
    return [entete] + corps


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


def _table_depuis_geometrie(pages: list[dict], min_rows: int, min_cols: int):
    """Reconstruction d'un tableau à partir des boîtes RapidOCR.

    Heuristique franchement faillible, et c'est assumé : elle retient la largeur
    de ligne la plus fréquente et jette tout le reste. Un tableau à cellules
    fusionnées, à cellules sur deux lignes, ou noyé dans plus de texte courant
    que de lignes de données n'en ressort pas. C'est le prix du seul moteur qui
    n'a ni GPU ni réseau — les moteurs 1 et 2 rendent la structure directement.
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
    return table_rows


def _dataframe(table: list[list[str]]):
    """Construit le DataFrame à partir d'une table (en-tête + corps)."""
    header = table[0]
    largeur = len(header)

    # Noms de colonnes uniques et non vides
    seen = {}
    columns = []
    for index, name in enumerate(header):
        clean = (name or "").strip() or f"col_{index + 1}"
        count = seen.get(clean, 0)
        columns.append(clean if count == 0 else f"{clean}_{count}")
        seen[clean] = count + 1

    # Une cellule fusionnée ou une bordure manquante décale une ligne : on la
    # ramène à la largeur de l'en-tête plutôt que de rejeter la table entière.
    body = [
        (row + [""] * largeur)[:largeur]
        for row in table[1:]
        if any(str(cellule).strip() for cellule in row)
    ]
    if not body:
        return None

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


def extract_table_from_ocr(pages: list[dict], min_rows: int = 3, min_cols: int = 2):
    """Tente de reconstruire un tableau à partir des pages reconnues.

    Deux sources selon le moteur qui a servi : les tables markdown émises par
    Unlimited-OCR ou par la transcription vision, sinon la géométrie des boîtes
    de RapidOCR. Le markdown est tenté d'abord — quand il existe, c'est le
    modèle qui a lu la structure, pas nous qui la devinons.

    Dans les deux cas, les pages sont recollées : un tableau long s'étale sur
    plusieurs pages et doit ressortir entier.

    Retourne un DataFrame, ou None si aucune table crédible n'est trouvée.
    """
    table = _table_depuis_markdown(pages, min_rows, min_cols)
    if table is None:
        table = _table_depuis_geometrie(pages, min_rows, min_cols)
    return _dataframe(table) if table else None


def extract_table_from_scanned_pdf(file_bytes: bytes, model: str | None = None):
    """Raccourci : OCR du PDF puis reconstruction du tableau, ou None."""
    return extract_table_from_ocr(ocr_pdf_pages(file_bytes, model=model))
