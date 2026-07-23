import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.config import PROVIDER_ENV_VARS, PROVIDER_MODELS, get_api_key, set_api_key
from app.services.provider_test import verify_provider_key

logger = logging.getLogger("app.settings")

router = APIRouter()


class ApiKeyRequest(BaseModel):
    provider: str
    model: str
    api_key: str


@router.get("/settings/providers")
async def list_providers():
    return {
        "providers": [
            {
                "id": provider,
                "configured": bool(get_api_key(provider)),
                "models": PROVIDER_MODELS.get(provider, []),
            }
            for provider in PROVIDER_ENV_VARS
        ]
    }


@router.post("/settings/api-key")
async def save_api_key(payload: ApiKeyRequest):
    if payload.provider not in PROVIDER_ENV_VARS:
        raise HTTPException(status_code=400, detail="Fournisseur inconnu.")
    api_key = payload.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Clé API vide.")
    model = payload.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Modèle manquant.")

    try:
        verify_provider_key(payload.provider, model, api_key)
    except Exception as exc:
        logger.warning("Échec de vérification de la clé API %s: %s", payload.provider, exc)
        raise HTTPException(status_code=400, detail=f"La clé API n'a pas pu être validée : {exc}")

    set_api_key(payload.provider, api_key)
    return {"status": "ok", "provider": payload.provider}
