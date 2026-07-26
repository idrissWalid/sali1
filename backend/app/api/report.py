import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from app.services.report_service import build_pdf_report, build_word_report
from app.services.session_service import get_session, get_report_data

router = APIRouter()

REPORT_KEYWORDS = [
    "rapport", "génère un rapport", "générer un rapport",
    "exporte", "télécharge", "word", "pdf", "document"
]

def is_report_request(message: str) -> bool:
    return any(kw in message.lower() for kw in REPORT_KEYWORDS)

class ReportRequest(BaseModel):
    session_id: str
    title: str = "Rapport d'analyse de données"
    institution: str = "CITADEL — Ouagadougou, Burkina Faso"
    format: str = "pdf"  # "pdf" ou "word"

@router.post("/report")
async def generate_report(request: ReportRequest):
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable.")

    data = get_report_data(request.session_id)

    if request.format == "pdf":
        pdf_bytes = await asyncio.to_thread(
            build_pdf_report,
            title=request.title,
            institution=request.institution,
            filename=data.get("filename", ""),
            analysis_text=data.get("analysis", ""),
            messages=data.get("messages", []),
            images_b64=data.get("images", []),
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="rapport_analyse.pdf"'},
        )

    elif request.format == "word":
        docx_bytes = await asyncio.to_thread(
            build_word_report,
            title=request.title,
            institution=request.institution,
            filename=data.get("filename", ""),
            analysis_text=data.get("analysis", ""),
            messages=data.get("messages", []),
            images_b64=data.get("images", []),
        )
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="rapport_analyse.docx"'},
        )

    else:
        raise HTTPException(status_code=400, detail="Format invalide. Utilisez 'pdf' ou 'word'.")
