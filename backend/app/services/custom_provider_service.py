"""custom_provider_service.py — Fournisseur « Autre », compatible OpenAI.

Même rôle que `openai_service` / `groq_service` / `mistral_service`, à une
différence près : l'URL de base n'est pas une constante du code mais un réglage
saisi par l'utilisateur (voir /api/settings/api-key et `core.config`). Cela
couvre tout point d'entrée qui parle le protocole d'OpenAI — vLLM, LM Studio,
OpenRouter, Together, un proxy interne d'entreprise…
"""

from app.core.config import get_api_key, get_custom_base_url
from app.services.openai_compatible import complete as _complete


class FournisseurPersonnaliseIncomplet(Exception):
    """URL de base absente : le fournisseur n'a jamais été configuré."""


def base_url() -> str:
    url = get_custom_base_url()
    if not url:
        raise FournisseurPersonnaliseIncomplet(
            "Aucune URL n'est enregistrée pour le fournisseur « Autre ». "
            "Renseignez-la dans Préférences → Modèle IA → Configurer l'API."
        )
    return url


def complete(prompt: str, model: str, history: list | None = None,
             system: str | None = None) -> str:
    return _complete(base_url(), get_api_key("custom"), model, prompt,
                     history=history, system=system, label="Autre")
