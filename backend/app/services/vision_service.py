"""vision_service.py — Lecture d'images par le fournisseur choisi par l'utilisateur.

Un document scanné dont l'OCR local n'a rien tiré ne peut être lu que par un
modèle multimodal. Auparavant ce cas appelait Gemini en dur, quel que soit le
modèle sélectionné : choisir Ollama en local n'empêchait pas les pages de partir
chez Google, et exigeait une clé Gemini.

Ici on route vers le modèle vision **du fournisseur déjà choisi**, et si celui-ci
n'a pas de vision on lève `VisionNonSupportee` — un refus explicite vaut mieux
qu'un contournement silencieux du choix de l'utilisateur.
"""

import base64
import logging

from app.core import config

logger = logging.getLogger("app.vision")


class VisionNonSupportee(Exception):
    """Le modèle sélectionné ne sait pas lire d'images.

    Porte un message destiné à l'utilisateur : il est remonté tel quel dans le
    chat, avec les options concrètes qui s'offrent à lui.
    """


# Familles multimodales, repérées par fragment de nom (les fournisseurs versionnent
# abondamment : « gpt-4o-2024-11-20 », « llava:13b »…). Volontairement conservateur —
# en cas de doute on refuse, plutôt que d'échouer au milieu d'un appel payant.
_FRAGMENTS_VISION = (
    "gpt-4o", "gpt-4.1", "gpt-5", "o4-mini",          # OpenAI
    "claude-3", "claude-4", "claude-sonnet", "claude-opus", "claude-haiku",  # Anthropic
    "gemini",                                          # Google
    "pixtral", "mistral-medium-3", "mistral-small-3",  # Mistral
    "llava", "bakllava", "moondream", "llama3.2-vision", "llama-3.2-vision",
    "qwen2-vl", "qwen2.5-vl", "minicpm-v", "gemma3",   # Ollama / local
    "scout", "maverick",                               # Llama 4 (Groq)
)

# Modèles explicitement dépourvus de vision malgré un nom proche d'une famille
# multimodale — `mistral-small-latest` par exemple n'est pas la 3.x multimodale.
_SANS_VISION = (
    "mistral-small-latest", "mistral-large-latest", "open-mistral-nemo",
    "o3-mini", "gpt-4o-mini-tts", "gpt-4o-transcribe",
)


def supporte_vision(model: str | None) -> bool:
    """Le modèle sait-il lire des images ?"""
    nom = (model or "").split("/", 1)[-1].strip().lower()
    if not nom:
        return False
    if any(nom.startswith(x) for x in _SANS_VISION):
        return False
    return any(frag in nom for frag in _FRAGMENTS_VISION)


def message_refus(model: str) -> str:
    """Message montré à l'utilisateur quand son modèle ne lit pas les images."""
    return (
        f"Le modèle sélectionné (**{model}**) ne sait pas lire les images, et ce "
        f"document est un scan dont la reconnaissance de texte (OCR) n'a rien pu "
        f"extraire.\n\n"
        f"Trois options :\n"
        f"- choisir un modèle multimodal (Gemini, GPT-4o, Claude, ou un modèle "
        f"vision local comme llava / llama3.2-vision) ;\n"
        f"- fournir une version *texte* du document (PDF non scanné, Word) ;\n"
        f"- fournir un scan de meilleure qualité, que l'OCR pourra lire."
    )


def ask_vision(prompt: str, images: list[bytes], model: str | None = None,
               history: list | None = None, system: str | None = None) -> str:
    """Interroge le modèle multimodal du fournisseur choisi sur des images PNG.

    `system` remplace le prompt système de l'agent pour cet appel. Sans lui, les
    images sont lues par un « agent d'analyse de données » à qui l'on impose de
    conclure par des suggestions d'analyses complémentaires — ce qu'il faut pour
    répondre à une question, mais pas pour TRANSCRIRE une page : la transcription
    se retrouverait alors enrobée de commentaires. Voir `ocr_service`.

    Raises:
        VisionNonSupportee: si `model` n'est pas multimodal. L'appelant doit
            présenter le message à l'utilisateur plutôt que de basculer sur un
            autre fournisseur.
    """
    model = model or config.get_default_model()
    if not supporte_vision(model):
        raise VisionNonSupportee(message_refus(model))

    history = history or []
    if not images:
        raise ValueError("Aucune image à analyser.")

    if "/" in model:
        provider, nom_modele = model.split("/", 1)
    elif model.startswith("gemini"):
        provider, nom_modele = "gemini", model
    else:
        provider, nom_modele = "ollama", model

    logger.info("Vision via %s (%s) sur %d image(s)", provider, nom_modele, len(images))

    # Le prompt système de l'agent, remis à chaque fournisseur dans son emplacement
    # dédié. Auparavant seul le bras Gemini le posait (il le concaténait lui-même) :
    # lire le même scan avec Claude, GPT-4o ou un modèle vision local donnait donc
    # une réponse sans les règles de langue et de style de l'application.
    if system is None:
        from app.services.gemini_service import build_system_prompt
        system = build_system_prompt()

    if provider == "gemini":
        from app.services.gemini_service import ask_gemini_vision
        return ask_gemini_vision(prompt, images, history=history, model=nom_modele, system=system)
    if provider == "anthropic":
        return _vision_anthropic(prompt, images, nom_modele, history, system=system)
    if provider == "ollama":
        return _vision_ollama(prompt, images, nom_modele, system=system)
    if provider in ("openai", "groq", "mistral", "custom"):
        return _vision_openai_compatible(prompt, images, nom_modele, history, provider, system=system)

    raise VisionNonSupportee(
        f"Le fournisseur « {provider} » n'a pas de lecture d'images câblée dans "
        f"cette application. Choisissez un modèle Gemini, OpenAI, Anthropic, "
        f"Mistral, Groq ou un modèle vision local (Ollama)."
    )


def _b64(images: list[bytes]) -> list[str]:
    return [base64.b64encode(img).decode("utf-8") for img in images]


def _vision_openai_compatible(prompt: str, images: list[bytes], model: str,
                              history: list, provider: str, system: str | None = None) -> str:
    """Format « image_url » avec data URI, commun à OpenAI, Groq et Mistral."""
    import requests

    bases = {
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "mistral": "https://api.mistral.ai/v1",
    }
    # Le fournisseur « Autre » est le seul dont l'URL vient des réglages.
    base = bases.get(provider) or config.get_custom_base_url()
    if not base:
        raise ValueError(
            "Aucune URL enregistrée pour le fournisseur « Autre ». "
            "Renseignez-la dans Préférences → Modèle IA → Configurer l'API."
        )
    api_key = config.get_api_key(provider)
    if not api_key:
        raise ValueError(f"Clé API {provider} manquante. Configurez-la dans les paramètres.")

    contenu = [{"type": "text", "text": prompt}]
    for b64 in _b64(images):
        contenu.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    for msg in (history or [])[-10:]:
        role = "assistant" if msg["role"] in ("model", "assistant") else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": contenu})

    response = requests.post(
        f"{base}/chat/completions",
        json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 2048},
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _vision_anthropic(prompt: str, images: list[bytes], model: str, history: list,
                      system: str | None = None) -> str:
    """Format « source.base64 » propre à l'API Messages d'Anthropic."""
    import requests

    api_key = config.get_api_key("anthropic")
    if not api_key:
        raise ValueError("Clé API Anthropic manquante. Configurez-la dans les paramètres.")

    contenu = [
        {"type": "image",
         "source": {"type": "base64", "media_type": "image/png", "data": b64}}
        for b64 in _b64(images)
    ]
    contenu.append({"type": "text", "text": prompt})

    messages = []
    for msg in (history or [])[-10:]:
        role = "assistant" if msg["role"] in ("model", "assistant") else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": contenu})

    payload = {"model": model, "max_tokens": 2048, "messages": messages}
    if system:
        payload["system"] = system

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        json=payload,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["content"][0]["text"]


def _vision_ollama(prompt: str, images: list[bytes], model: str,
                   system: str | None = None) -> str:
    """Ollama accepte les images en base64 dans le champ `images` de /api/generate.

    Rien ne sort de la machine : c'est l'option souveraine quand le document est
    sensible.
    """
    import requests

    from app.services.ollama_service import OLLAMA_API_URL

    payload = {
        "model": model,
        "prompt": prompt,
        "images": _b64(images),
        "stream": False,
        "think": False,
        "keep_alive": "5m",
    }
    if system:
        payload["system"] = system

    response = requests.post(
        OLLAMA_API_URL,
        json=payload,
        timeout=300,
    )
    response.raise_for_status()
    data = response.json()
    return (data.get("response") or data.get("thinking") or "").strip()
