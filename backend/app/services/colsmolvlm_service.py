"""
colsmolvlm_service.py — Retrieval visuel de documents via ColSmolVLM.

Utilisé en fallback quand un PDF n'a aucun texte extractible (scan, photo) :
chaque page est rendue en image et encodée en embeddings multi-vecteurs
(late interaction, style ColBERT/ColPali). La question de l'utilisateur est
encodée de la même façon, et un score de similarité par page permet de
retrouver les pages pertinentes. Ces pages sont ensuite envoyées telles
quelles (images) à un LLM multimodal (Gemini) pour la génération de la
réponse — il n'y a jamais de texte OCR intermédiaire.
"""

from pathlib import Path

import fitz  # pymupdf
import torch
from PIL import Image

MODEL_NAME = "vidore/colsmolvlm-v0.1"
DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "visual_docs"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_model = None
_processor = None


def _get_model():
    global _model, _processor
    if _model is None:
        from colpali_engine.models import ColIdefics3, ColIdefics3Processor
        _model = ColIdefics3.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.float32,
            device_map="cpu",
        ).eval()
        _processor = ColIdefics3Processor.from_pretrained(MODEL_NAME)
    return _model, _processor


def render_pdf_to_images(file_bytes: bytes, dpi: int = 150) -> list:
    """Rasterise chaque page d'un PDF en image PIL (via PyMuPDF, sans dépendance système)."""
    images = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        images.append(img)
    doc.close()
    return images


def index_visual_document(session_id: str, file_bytes: bytes) -> dict:
    """Rend les pages en images, calcule leurs embeddings ColSmolVLM et les persiste sur disque."""
    try:
        images = render_pdf_to_images(file_bytes)
        if not images:
            return {"status": "error", "message": "Aucune page trouvée dans le document."}

        model, processor = _get_model()
        session_dir = DATA_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        page_embeddings = []
        with torch.no_grad():
            for i, img in enumerate(images):
                img.save(session_dir / f"page_{i}.png", "PNG")
                batch = processor.process_images([img]).to(model.device)
                emb = model(**batch)[0]
                page_embeddings.append(emb.to(torch.float32).cpu())

        torch.save(page_embeddings, session_dir / "embeddings.pt")

        return {"status": "ok", "n_pages": len(images)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def retrieve_visual_pages(session_id: str, question: str, top_k: int = 3) -> list:
    """Retourne les top_k pages (bytes PNG + numéro + score) les plus pertinentes pour la question."""
    session_dir = DATA_DIR / session_id
    emb_path = session_dir / "embeddings.pt"
    if not emb_path.exists():
        return []

    try:
        model, processor = _get_model()
        page_embeddings = torch.load(emb_path, weights_only=False)

        with torch.no_grad():
            query_batch = processor.process_queries([question]).to(model.device)
            query_emb = model(**query_batch)[0].to(torch.float32).cpu()

        scores = processor.score_multi_vector([query_emb], page_embeddings)[0].tolist()
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for idx in ranked:
            img_path = session_dir / f"page_{idx}.png"
            if img_path.exists():
                with open(img_path, "rb") as f:
                    results.append({"page": idx + 1, "image_bytes": f.read(), "score": scores[idx]})
        return results
    except Exception:
        return []


def has_visual_index(session_id: str) -> bool:
    return (DATA_DIR / session_id / "embeddings.pt").exists()
