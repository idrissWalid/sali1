from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any
import json
import os
from app.core.database import get_db_connection
from app.services.session_service import get_session, rename_session
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

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Récupérer les informations pour nettoyer les fichiers et ChromaDB
    cursor.execute("SELECT type, file_path FROM sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Session introuvable.")
        
    # Supprimer les messages et la session de SQLite
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()
    
    # Supprimer le fichier physique
    file_path = row["file_path"]
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"Erreur de suppression du fichier {file_path}: {e}")
            
    # Supprimer la collection ChromaDB si c'est un document
    if row["type"] == "document":
        try:
            chroma_client.delete_collection(name=f"session_{session_id}")
        except Exception as e:
            print(f"Erreur de suppression de la collection ChromaDB session_{session_id}: {e}")
            
    return {"status": "ok", "message": "Session supprimée avec succès."}
