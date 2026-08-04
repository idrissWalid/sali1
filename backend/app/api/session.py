from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any
import json
from app.core.database import get_db_connection
from app.services.session_service import get_session, rename_session, delete_session_cascade
from app.services.rag_service import chroma_client

router = APIRouter()

class SessionListItem(BaseModel):
    id: str
    title: str
    type: str
    filename: Optional[str] = None
    created_at: str

class SessionRenameRequest(BaseModel):
    title: str

class MessageItem(BaseModel):
    role: str
    text: str
    images: Optional[List[str]] = []
    sources: Optional[List[dict]] = []

class SessionDetails(BaseModel):
    id: str
    title: str
    type: str
    filename: Optional[str] = None
    initial_analysis: Optional[str] = None
    data_profile: Optional[Any] = None
    data_stats: Optional[Any] = None
    data_preview: Optional[Any] = None
    messages: List[MessageItem] = []

@router.get("/sessions", response_model=List[SessionListItem])
async def list_sessions():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, type, filename, created_at FROM sessions ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    sessions = []
    for r in rows:
        sessions.append({
            "id": r["id"],
            "title": r["title"] or "Nouvelle session",
            "type": r["type"],
            "filename": r["filename"],
            "created_at": r["created_at"]
        })
    return sessions

@router.get("/sessions/{session_id}", response_model=SessionDetails)
async def get_session_details(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role, content as text, images, sources FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    msg_rows = cursor.fetchall()
    conn.close()
    
    messages = []
    for m in msg_rows:
        messages.append({
            "role": m["role"],
            "text": m["text"],
            "images": json.loads(m["images"]) if m["images"] else [],
            "sources": json.loads(m["sources"]) if m["sources"] else []
        })
        
    return SessionDetails(
        id=session["id"],
        title=session["title"] or "Nouvelle session",
        type=session["type"],
        filename=session["filename"],
        initial_analysis=session["initial_analysis"],
        data_profile=session["data_profile"],
        data_stats=session["data_stats"],
        data_preview=session["data_preview"],
        messages=messages
    )

@router.patch("/sessions/{session_id}")
async def rename_session_endpoint(session_id: str, request: SessionRenameRequest):
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Le titre ne peut pas être vide.")

    updated = rename_session(session_id, title)
    if not updated:
        raise HTTPException(status_code=404, detail="Session introuvable.")

    return {"status": "ok", "title": title}

class FusionRequest(BaseModel):
    base_id: str
    ajout_id: str


@router.get("/sessions/{session_id}/datasets")
async def list_session_datasets(session_id: str):
    """Fichiers rattachés à une session, et ceux qui pourraient être fusionnés.

    Une session porte souvent plusieurs fichiers — un jeu de données et ses
    métadonnées, ou un tableau livré en deux parties. `fusionnables` signale
    les paires de structure identique, pour que l'interface propose la
    concaténation sans jamais la décider seule.
    """
    from app.services.session_service import jeux_fusionnables, list_datasets

    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session introuvable.")

    jeux = list_datasets(session_id)
    return {
        "datasets": jeux,
        "fusionnables": {
            jeu["id"]: [autre["id"] for autre in jeux_fusionnables(session_id, jeu["id"])]
            for jeu in jeux
        },
    }


@router.post("/sessions/{session_id}/datasets/merge")
async def merge_session_datasets(session_id: str, payload: FusionRequest):
    """Concatène deux fichiers de même structure en un nouveau jeu.

    Les deux sources sont conservées : la fusion s'annule en supprimant le jeu
    produit.
    """
    from app.services.session_service import fusionner_jeux

    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Session introuvable.")

    resultat = fusionner_jeux(session_id, payload.base_id, payload.ajout_id)
    if resultat.get("status") != "ok":
        raise HTTPException(status_code=400, detail=resultat.get("message", "Fusion impossible."))
    return resultat


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    # Supprime la session, ses messages, ses datasets/modèles secondaires (via
    # cascade SQL) et les fichiers physiques associés.
    result = delete_session_cascade(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session introuvable.")

    # Stockage spécifique au type de session, non couvert par delete_session_cascade.
    if result["type"] == "document":
        try:
            chroma_client.delete_collection(name=f"session_{session_id}")
        except Exception as e:
            print(f"Erreur de suppression de la collection ChromaDB session_{session_id}: {e}")

    return {"status": "ok", "message": "Session supprimée avec succès."}
