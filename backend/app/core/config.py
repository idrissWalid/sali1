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
    # Fournisseur « Autre » : n'importe quel point d'entrée compatible OpenAI
    # (vLLM, LM Studio, OpenRouter, Together, un proxy interne…). Contrairement
    # aux précédents, son URL et son modèle ne sont pas connus à l'avance :
    # l'utilisateur les saisit, et ils sont persistés ci-dessous.
    "custom": "CUSTOM_API_KEY",
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
    # Vide à dessein : le modèle du fournisseur « Autre » est saisi par
    # l'utilisateur, pas choisi dans une liste. Il est lu via get_custom_model().
    "custom": [],
}

# ── Fournisseur « Autre » ────────────────────────────────────────────────────
# Deux réglages en plus de la clé, persistés dans .env comme le reste pour
# survivre à un redémarrage sans base de données.
CUSTOM_BASE_URL_ENV_VAR = "CUSTOM_API_BASE_URL"
CUSTOM_MODEL_ENV_VAR = "CUSTOM_API_MODEL"


def normaliser_base_url(url: str) -> str:
    """URL de base exploitable par `openai_compatible.complete`.

    Celui-ci concatène « /chat/completions » : une URL finissant par un slash
    donnerait « //chat/completions », et coller l'URL complète trouvée dans la
    documentation d'un fournisseur — l'erreur la plus probable — donnerait
    « /chat/completions/chat/completions ». Les deux sont corrigés ici plutôt
    que reprochés à l'utilisateur.
    """
    url = (url or "").strip().rstrip("/")
    for suffixe in ("/chat/completions", "/completions"):
        if url.endswith(suffixe):
            url = url[: -len(suffixe)]
            break
    return url


def get_custom_base_url() -> str | None:
    return os.getenv(CUSTOM_BASE_URL_ENV_VAR) or None


def set_custom_base_url(value: str) -> None:
    value = normaliser_base_url(value)
    if not value:
        raise ValueError("URL de base vide.")
    ENV_PATH.touch(exist_ok=True)
    _dotenv_set_key(str(ENV_PATH), CUSTOM_BASE_URL_ENV_VAR, value)
    os.environ[CUSTOM_BASE_URL_ENV_VAR] = value


def get_custom_model() -> str | None:
    return os.getenv(CUSTOM_MODEL_ENV_VAR) or None


def set_custom_model(value: str) -> None:
    value = (value or "").strip()
    if not value:
        raise ValueError("Nom de modèle vide.")
    ENV_PATH.touch(exist_ok=True)
    _dotenv_set_key(str(ENV_PATH), CUSTOM_MODEL_ENV_VAR, value)
    os.environ[CUSTOM_MODEL_ENV_VAR] = value

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
