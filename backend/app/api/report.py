import asyncio
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from app.services.report_service import (
    build_pdf_report, build_word_report, build_powerpoint_report,
)
from app.services.session_service import get_session, get_report_data

router = APIRouter()
logger = logging.getLogger(__name__)

# Constructeur, type MIME et nom de fichier de chaque format proposé.
FORMATS = {
    "pdf": (
        build_pdf_report,
        "application/pdf",
        "rapport_analyse.pdf",
    ),
    "word": (
        build_word_report,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "rapport_analyse.docx",
    ),
    "powerpoint": (
        build_powerpoint_report,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "rapport_analyse.pptx",
    ),
}

class ReportRequest(BaseModel):
    session_id: str
    title: str = "Rapport d'analyse de données"
    # Conservé pour les anciens clients, mais l'identité institutionnelle n'est
    # plus imprimée automatiquement dans les livrables.
    institution: str = ""
    format: str = "pdf"  # "pdf", "word" ou "powerpoint"
    # Consigne libre saisie dans la modale « Générer un rapport ». Champ à part
    # entière : concaténée au titre, elle n'orientait pas la rédaction et
    # s'imprimait sur la page de garde.
    key_points: str = ""
    # Data URL ou contenu base64 d'un PNG/JPEG facultatif. Le service le valide,
    # le normalise et ne l'utilise que sur la couverture.
    logo_b64: str | None = None
    model: str | None = None  # modèle LLM ; à défaut, le modèle par défaut de l'instance

@router.post("/report")
async def generate_report(request: ReportRequest):
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable.")

    if request.format not in FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Format invalide. Utilisez {', '.join(sorted(FORMATS))}.",
        )

    data = get_report_data(request.session_id)

    builder, media_type, nom_fichier = FORMATS[request.format]
    try:
        content = await asyncio.to_thread(
            builder,
            title=request.title,
            institution=request.institution,
            filename=data.get("filename", ""),
            analysis_text=data.get("analysis", ""),
            messages=data.get("messages", []),
            images_b64=data.get("images", []),
            model=request.model,
            key_points=request.key_points,
            profile=data.get("profile", {}),
            stats=data.get("stats", {}),
            models=data.get("models", []),
            logo_b64=request.logo_b64,
        )
    except Exception as exc:
        # Un échec du modèle produisait jusqu'ici un rapport de remplissage,
        # livré sans que rien ne signale que la rédaction n'avait pas eu lieu.
        logger.exception("Génération du rapport %s échouée", request.format)
        raise HTTPException(
            status_code=502,
            detail=f"La rédaction du rapport a échoué : {exc}",
        ) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )
