import torch  # Import torch first to avoid DLL initialization error (WinError 1114)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.chat import router as chat_router
from app.api.upload import router as upload_router
from app.api.report import router as report_router
from app.api.session import router as session_router
from app.api.audio import router as audio_router
from app.api.settings import router as settings_router
from app.core import config
from app.core.database import init_db
from app.core.json_utils import SafeJSONResponse

# Initialisation de la base de données SQLite
init_db()

app = FastAPI(
    title="No-Code Data Intelligence",
    description="Agent IA d'analyse de données pour institutions africaines",
    version="0.1.0",
    # Les payloads issus de pandas/statsmodels peuvent contenir des NaN/Inf, que
    # le JSON standard n'admet pas. Sans ça la réponse échoue en ValueError.
    default_response_class=SafeJSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_AUTH_KEY_HEADER = "X-API-Key"
# Endpoints publics même quand une clé est configurée : sondes de vie utilisées
# par l'orchestrateur/la plateforme de déploiement, qui n'a pas la clé.
_PUBLIC_PATHS = {"/", "/health"}


@app.middleware("http")
async def enforce_api_key(request: Request, call_next):
    """Exige l'en-tête X-API-Key sur toute requête si API_AUTH_KEY est définie
    dans backend/.env. Sans cette variable (cas par défaut, usage local),
    l'authentification reste désactivée — voir README."""
    expected_key = config.get_api_auth_key()
    if (
        not expected_key
        or request.method == "OPTIONS"  # préflight CORS : jamais d'en-tête personnalisé
        or request.url.path in _PUBLIC_PATHS
    ):
        return await call_next(request)

    if request.headers.get(API_AUTH_KEY_HEADER) != expected_key:
        return JSONResponse(status_code=401, content={"detail": "Clé API invalide ou manquante."})

    return await call_next(request)


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


@app.get("/api/dashboard/interpret/{session_id}")
async def interpret_dashboard_variable(
    session_id: str,
    variable: str,
    dataset_id: str | None = None,
    model: str | None = None,
):
    """Interprétation en langage naturel d'une variable, affichée à côté de son
    graphique dans le dashboard. Change avec la variable sélectionnée."""
    from app.services.analysis_service import interpret_variable
    from fastapi import HTTPException

    result = await interpret_variable(session_id, variable, dataset_id=dataset_id, model=model)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/sessions/{session_id}/datasets")
async def list_session_datasets(session_id: str):
    """Jeux de données consultables dans une session (le dashboard s'en sert
    pour alimenter son sélecteur)."""
    from app.services.session_service import list_datasets
    return {"datasets": list_datasets(session_id)}