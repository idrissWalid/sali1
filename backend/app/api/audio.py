import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services.whisper_service import transcribe_audio

router = APIRouter(
    prefix="/audio",
    tags=["audio"]
)

@router.post("/transcribe")
async def transcribe_audio_endpoint(file: UploadFile = File(...)):
    """
    Endpoint pour la reconnaissance vocale (Speech-to-Text).
    Reçoit un fichier audio et retourne le texte transcrit via Whisper.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")
        
    try:
        content = await file.read()
        result = await asyncio.to_thread(transcribe_audio, content, file.filename)
        
        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=result["message"])
            
        return {"text": result["text"]}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
