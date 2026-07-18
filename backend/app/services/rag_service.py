import io
import os
import uuid

import numpy as np
from pypdf import PdfReader

try:
    import chromadb
except Exception:  # pragma: no cover - optional dependency
    chromadb = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional dependency
    SentenceTransformer = None

# Configuration ChromaDB persistent local
CHROMA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/chroma"))
os.makedirs(CHROMA_PATH, exist_ok=True)
chroma_client = None
if chromadb is not None:
    try:
        chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
    except Exception as e:
        print("Could not initialize ChromaDB:", e)


class SimpleEmbeddingModel:
    """Fallback embedding model used when sentence-transformers is unavailable."""

    def encode(self, texts):
        vectors = []
        for text in texts:
            tokens = [token.lower() for token in text.replace("\n", " ").split() if token]
            vector = np.zeros(32, dtype=float)
            for token in set(tokens):
                seed = 0
                for char in token:
                    seed = (seed * 31 + ord(char)) % 1000003
                vector[seed % 32] += 1.0
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector /= norm
            vectors.append(vector)
        return np.array(vectors)


# Modèle d'embeddings léger et multilingue
embedding_model = None

def get_embedding_model():
    global embedding_model
    if embedding_model is None:
        MODEL_PATH = os.path.join(os.path.dirname(__file__), "../../models/embedding_model")
        if SentenceTransformer is not None:
            try:
                embedding_model = SentenceTransformer(MODEL_PATH)
            except Exception:
                try:
                    embedding_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
                except Exception as e:
                    print("Could not load sentence-transformers:", e)
        if embedding_model is None:
            embedding_model = SimpleEmbeddingModel()
    return embedding_model


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extrait le texte d'un PDF (conservé pour compatibilité rétrograde)."""
    return _extract_pdf(file_bytes)


def _extract_pdf(file_bytes: bytes) -> str:
    text_parts = []
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_parts.append(page_text.strip())
    except Exception as e:
        print("Primary PDF extraction failed:", e)

    if text_parts:
        return "\n\n".join(text_parts).strip()

    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text and page_text.strip():
                    text_parts.append(page_text.strip())
    except Exception as e:
        print("PDF fallback extraction failed:", e)

    return "\n\n".join(text_parts).strip()


def _extract_docx(file_bytes: bytes) -> str:
    """Extrait le texte d'un fichier Word (.docx)."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs).strip()
    except ImportError:
        print("python-docx non installé. pip install python-docx")
        return ""
    except Exception as e:
        print("DOCX extraction failed:", e)
        return ""


def _extract_text(file_bytes: bytes) -> str:
    """Extrait le texte d'un fichier TXT ou Markdown."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def extract_text_from_document(file_bytes: bytes, filename: str = "") -> str:
    """Extrait le texte de n'importe quel type de document supporté."""
    ext = os.path.splitext(filename)[1].lower() if filename else ""
    if ext == ".pdf" or not ext:
        return _extract_pdf(file_bytes)
    elif ext == ".docx":
        return _extract_docx(file_bytes)
    elif ext in (".md", ".txt"):
        return _extract_text(file_bytes)
    else:
        # Fallback : essaie PDF puis texte brut
        result = _extract_pdf(file_bytes)
        if not result.strip():
            result = _extract_text(file_bytes)
        return result

def chunk_page_text(page_text: str, page_number: int, chunk_size: int = 400, overlap: int = 50) -> list:
    words = page_text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append({
            "text": chunk,
            "page": page_number
        })
        i += chunk_size - overlap
    return chunks

def index_document(session_id: str, file_bytes: bytes, filename: str) -> dict:
    try:
        all_chunks = []
        extracted_text = extract_text_from_document(file_bytes, filename)
        if extracted_text.strip():
            all_chunks = chunk_page_text(extracted_text, 1)

        if not all_chunks:
            return {
                "status": "ok",
                "chunks_indexed": 0,
                "filename": filename,
                "message": "Aucun texte extractible dans ce PDF."
            }

        if chroma_client is None:
            return {
                "status": "ok",
                "chunks_indexed": len(all_chunks),
                "filename": filename,
                "message": "Indexation vectorielle indisponible, texte conservé pour le résumé."
            }

        # Créer une collection ChromaDB par session
        collection = chroma_client.get_or_create_collection(
            name=f"session_{session_id}"
        )

        # Générer les embeddings et indexer
        documents = [c["text"] for c in all_chunks]
        metadatas = [{"page": c["page"], "filename": filename} for c in all_chunks]
        embeddings = get_embedding_model().encode(documents).tolist()
        ids = [str(uuid.uuid4()) for _ in documents]

        collection.add(
            documents=documents,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas
        )

        return {
            "status": "ok",
            "chunks_indexed": len(documents),
            "filename": filename
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def retrieve_context_with_sources(session_id: str, question: str, top_k: int = 4) -> tuple[str, list[dict]]:
    if chroma_client is None:
        return "", []
    try:
        collection = chroma_client.get_collection(
            name=f"session_{session_id}"
        )
        question_embedding = get_embedding_model().encode([question]).tolist()
        results = collection.query(
            query_embeddings=question_embedding,
            n_results=top_k
        )

        fragments = results["documents"][0]
        metadatas = results["metadatas"][0]

        sources = []
        for doc, meta in zip(fragments, metadatas):
            sources.append({
                "page": meta.get("page", 1),
                "text": doc
            })

        context = "\n\n---\n\n".join(fragments)
        return context, sources
    except Exception:
        return "", []

def retrieve_context(session_id: str, question: str, top_k: int = 4) -> str:
    context, _ = retrieve_context_with_sources(session_id, question, top_k)
    return context

def _llm_summarize(prompt: str, model: str = "gemma2:latest") -> str:
    try:
        from app.services.gemini_service import ask_gemini
        from app.services.ollama_service import ask_ollama

        if model and model.startswith("gemini"):
            return ask_gemini(prompt, model=model)
        return ask_ollama(prompt, model=model)
    except Exception as e:
        print("LLM summarization failed:", e)
        return ""


def get_document_chunks(session_id: str, max_chunks: int = 48) -> list[str]:
    if chroma_client is None:
        return []
    try:
        collection = chroma_client.get_collection(name=f"session_{session_id}")
        results = collection.get(limit=max_chunks)
        documents = results.get("documents", [])
        if documents and isinstance(documents[0], list):
            return documents[0]
        return documents if isinstance(documents, list) else []
    except Exception as e:
        print("Could not retrieve document chunks:", e)
        return []


def summarize_document(session_id: str, model: str = "gemma2:latest") -> str:
    chunks = get_document_chunks(session_id)
    if not chunks:
        return ""
    if len(chunks) <= 6:
        return "\n\n".join(chunks)

    batch_summaries = []
    max_batch_size = 6
    max_batches = 8
    batch_count = min((len(chunks) + max_batch_size - 1) // max_batch_size, max_batches)

    for batch_index in range(batch_count):
        start = batch_index * max_batch_size
        batch = chunks[start:start + max_batch_size]
        prompt = f"""
Voici un extrait d'un document. Rédige un résumé clair et synthétique en français du passage entier.
Ne commence pas par une introduction (pas de 'Bonjour', 'Voici', 'En tant que ...').

{chr(10).join(batch)}

Résumé :
"""
        summary = _llm_summarize(prompt, model)
        if summary.strip():
            batch_summaries.append(summary.strip())

    if not batch_summaries:
        return ""
    if len(batch_summaries) == 1:
        return batch_summaries[0]

    combined_prompt = f"""
Tu disposes des résumés intermédiaires de plusieurs parties d'un document.
Regroupe-les et rédige un résumé final unique en français.
Ne commence pas par des formules d'introduction ; va directement à l'essentiel.

{chr(10).join(batch_summaries)}

Résumé final :
"""
    final_summary = _llm_summarize(combined_prompt, model)
    if final_summary.strip():
        return final_summary.strip()
    return "\n\n".join(batch_summaries)
