import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.config import (
    PROVIDER_ENV_VARS, PROVIDER_MODELS, get_api_key, set_api_key,
    get_default_model, set_default_model,
    get_custom_base_url, set_custom_base_url,
    get_custom_model, set_custom_model, normaliser_base_url,
)
from app.services.provider_test import verify_provider_key

logger = logging.getLogger("app.settings")

router = APIRouter()


class ApiKeyRequest(BaseModel):
    provider: str
    model: str
    api_key: str
    # Uniquement pour le fournisseur « Autre », dont le point d'entrée n'est pas
    # connu du code. Ignoré pour les fournisseurs à URL fixe.
    base_url: str | None = None


class DefaultModelRequest(BaseModel):
    model: str


@router.get("/settings/providers")
async def list_providers():
    def decrire(provider: str) -> dict:
        # Le fournisseur « Autre » n'a pas de catalogue : son unique modèle est
        # celui que l'utilisateur a saisi. On le renvoie dans `models` pour que
        # l'interface préremplisse le formulaire, et l'URL avec.
        if provider == "custom":
            modele = get_custom_model()
            return {
                "id": provider,
                "configured": bool(get_api_key(provider)),
                "models": [modele] if modele else [],
                "base_url": get_custom_base_url() or "",
                "custom": True,
            }
        return {
            "id": provider,
            "configured": bool(get_api_key(provider)),
            "models": PROVIDER_MODELS.get(provider, []),
        }

    return {"providers": [decrire(provider) for provider in PROVIDER_ENV_VARS]}


@router.get("/settings/default-model")
async def get_default_model_setting():
    return {"model": get_default_model()}


@router.post("/settings/default-model")
async def save_default_model_setting(payload: DefaultModelRequest):
    model = payload.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Modèle manquant.")
    set_default_model(model)
    return {"status": "ok", "model": model}


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

    base_url = None
    if payload.provider == "custom":
        base_url = normaliser_base_url(payload.base_url or "")
        if not base_url:
            raise HTTPException(status_code=400, detail="URL de l'API manquante.")
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400,
                detail="L'URL doit commencer par http:// ou https:// (ex. https://api.exemple.com/v1).",
            )

    try:
        verify_provider_key(payload.provider, model, api_key, base_url=base_url)
    except Exception as exc:
        logger.warning("Échec de vérification de la clé API %s: %s", payload.provider, exc)
        raise HTTPException(status_code=400, detail=f"La clé API n'a pas pu être validée : {exc}")

    # Après la vérification seulement : un réglage à moitié écrit laisserait un
    # fournisseur inutilisable en .env, et l'URL sans la clé est déjà inutile.
    if payload.provider == "custom":
        set_custom_base_url(base_url)
        set_custom_model(model)
    set_api_key(payload.provider, api_key)
    return {"status": "ok", "provider": payload.provider}
