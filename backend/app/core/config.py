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
