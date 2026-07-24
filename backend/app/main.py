import torch  # Import torch first to avoid DLL initialization error (WinError 1114)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.chat import router as chat_router
from app.api.upload import router as upload_router
from app.api.report import router as report_router
from app.api.session import router as session_router
from app.api.audio import router as audio_router
from app.api.settings import router as settings_router
from app.core.database import init_db

# Initialisation de la base de données SQLite
init_db()

app = FastAPI(
    title="No-Code Data Intelligence",
    description="Agent IA d'analyse de données pour institutions africaines",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.models import router as models_router

app.include_router(chat_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(report_router, prefix="/api")
app.include_router(session_router, prefix="/api")
app.include_router(audio_router, prefix="/api")
app.include_router(models_router, prefix="/api")
app.include_router(settings_router, prefix="/api")

@app.get("/")
async def root():
    return {
        "message": "No-Code Data Intelligence API",
        "status": "running"
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/api/dashboard/data/{session_id}")
async def get_dashboard_data_endpoint(session_id: str, dataset_id: str | None = None):
    from app.services.analysis_service import get_dashboard_data
    from fastapi import HTTPException

    data = await get_dashboard_data(session_id, dataset_id=dataset_id)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


@app.get("/api/sessions/{session_id}/datasets")
async def list_session_datasets(session_id: str):
    """Jeux de données consultables dans une session (le dashboard s'en sert
    pour alimenter son sélecteur)."""
    from app.services.session_service import list_datasets
    return {"datasets": list_datasets(session_id)}