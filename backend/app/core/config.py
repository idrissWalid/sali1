import os
from pathlib import Path
from dotenv import load_dotenv, set_key as _dotenv_set_key

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(ENV_PATH)

PROVIDER_ENV_VARS = {
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Modèles proposés par fournisseur dans la configuration API (voir /api/settings).
# Convention de routage : "gemini" garde un nom nu, les autres fournisseurs sont
# préfixés "provider/model" (voir gemini_service.complete_text).
PROVIDER_MODELS = {
    "gemini": ["gemini-3.1-flash-lite-preview"],
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "o3-mini"],
    "mistral": ["mistral-large-latest", "mistral-small-latest", "open-mistral-nemo"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "anthropic": ["claude-sonnet-4-5", "claude-3-5-haiku-latest"],
}

# Conservé pour compatibilité avec le code existant qui importe cette constante.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Modèle LLM utilisé par défaut dans toute l'app quand aucun modèle n'est
# explicitement choisi par l'utilisateur (chat, entraînement de modèles, etc.).
# Configurable via /api/settings/default-model (persisté dans .env), donc modifiable
# sans redéploiement — d'où la lecture de l'env var à chaque appel plutôt qu'une
# constante figée à l'import.
DEFAULT_MODEL_ENV_VAR = "DEFAULT_LLM_MODEL"
FALLBACK_DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"


def get_default_model() -> str:
    return os.getenv(DEFAULT_MODEL_ENV_VAR) or FALLBACK_DEFAULT_MODEL


def set_default_model(value: str) -> None:
    value = (value or "").strip()
    if not value:
        raise ValueError("Modèle par défaut vide.")
    ENV_PATH.touch(exist_ok=True)
    _dotenv_set_key(str(ENV_PATH), DEFAULT_MODEL_ENV_VAR, value)
    os.environ[DEFAULT_MODEL_ENV_VAR] = value


def get_api_key(provider: str) -> str | None:
    env_var = PROVIDER_ENV_VARS.get(provider)
    if not env_var:
        return None
    return os.getenv(env_var) or None


def set_api_key(provider: str, value: str) -> None:
    env_var = PROVIDER_ENV_VARS.get(provider)
    if not env_var:
        raise ValueError(f"Fournisseur inconnu : {provider}")
    ENV_PATH.touch(exist_ok=True)
    _dotenv_set_key(str(ENV_PATH), env_var, value)
    os.environ[env_var] = value


# Clé partagée protégeant l'API elle-même (distincte des clés fournisseurs
# LLM ci-dessus). Non définie par défaut : usage local sans authentification.
# À définir dans backend/.env avant tout déploiement hors localhost — voir
# README. Lue à chaque requête (comme get_default_model) pour rester
# modifiable sans redéploiement.
API_AUTH_KEY_ENV_VAR = "API_AUTH_KEY"


def get_api_auth_key() -> str | None:
    return os.getenv(API_AUTH_KEY_ENV_VAR) or None
