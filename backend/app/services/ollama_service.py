import os
import logging
import requests

logger = logging.getLogger("app.ollama")

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
DEFAULT_OLLAMA_MODEL = os.getenv("DEFAULT_OLLAMA_MODEL", "gemma2:latest")
# Une limite basse évite de demander au serveur local de réserver un contexte
# disproportionné lorsqu'un profil de données et l'historique sont combinés.
MAX_PROMPT_CHARS = int(os.getenv("OLLAMA_MAX_PROMPT_CHARS", "16000"))
# Le pilote Vulkan de cette machine ne peut pas réserver le buffer nécessaire
# aux modèles installés. Forcer le CPU évite l'arrêt du serveur Ollama (500).
# Mettre OLLAMA_NUM_GPU=-1 dans le .env pour laisser Ollama exploiter un GPU
# correctement dimensionné.
OLLAMA_NUM_GPU = int(os.getenv("OLLAMA_NUM_GPU", "1"))
FALLBACK_MODELS = tuple(
    model.strip()
    for model in os.getenv("OLLAMA_FALLBACK_MODELS", "qwen3.5:0.8b,gemma:2b").split(",")
    if model.strip()
)


def _trim_prompt(prompt: str, limit: int = MAX_PROMPT_CHARS) -> str:
    """Conserve les consignes et la question, sans saturer le contexte Ollama."""
    prompt = (prompt or "").strip()
    if len(prompt) <= limit:
        return prompt

    head = int(limit * 0.65)
    tail = limit - head
    return (
        f"{prompt[:head]}\n\n"
        "[Contexte intermédiaire raccourci pour respecter la mémoire du modèle local.]\n\n"
        f"{prompt[-tail:]}"
    )


def _generate(model: str, prompt: str, num_ctx: int, num_predict: int) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "5m",
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "num_gpu": OLLAMA_NUM_GPU,
        },
    }
    logger.debug("Ollama request: model=%s num_ctx=%d num_predict=%d num_gpu=%s prompt_len=%d", model, num_ctx, num_predict, OLLAMA_NUM_GPU, len(prompt))
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=180)
        logger.debug("Ollama HTTP %s response (truncated 1000 chars): %s", response.status_code, response.text[:1000])
        response.raise_for_status()
        return response.json().get("response", "")
    except requests.RequestException as e:
        logger.exception("Erreur lors de l'appel à Ollama: %s", str(e))
        raise


def ask_ollama(prompt: str, model: str | None = None) -> str:
    """Interroge Ollama avec un contexte borné et un repli mémoire en cas de 500."""
    selected_model = (model or DEFAULT_OLLAMA_MODEL).strip()
    safe_prompt = _trim_prompt(prompt)

    try:
        return _generate(selected_model, safe_prompt, num_ctx=4096, num_predict=512)
    except requests.HTTPError as error:
        # Ollama retourne typiquement 500 lorsqu'il ne peut pas réserver le
        # contexte demandé. Une seconde tentative, plus compacte, reste utile
        # pour les machines ayant peu de RAM/VRAM.
        if error.response is not None and error.response.status_code == 500:
            error_text = error.response.text.lower()
            resource_error = any(term in error_text for term in ("allocate", "memory", "buffer", "out of memory"))

            if resource_error:
                for fallback_model in FALLBACK_MODELS:
                    if fallback_model == selected_model:
                        continue
                    try:
                        return _generate(
                            fallback_model,
                            _trim_prompt(safe_prompt, limit=7500),
                            num_ctx=2048,
                            num_predict=384,
                        )
                    except requests.RequestException:
                        continue

            try:
                return _generate(
                    selected_model,
                    _trim_prompt(safe_prompt, limit=7500),
                    num_ctx=2048,
                    num_predict=384,
                )
            except requests.RequestException as retry_error:
                detail = retry_error.response.text[:500] if getattr(retry_error, "response", None) is not None else str(retry_error)
                return f"Erreur Ollama ({selected_model}) : {detail}"

        detail = error.response.text[:500] if error.response is not None else str(error)
        return f"Erreur Ollama ({selected_model}) : {detail}"
    except requests.RequestException as error:
        return f"Erreur Ollama ({selected_model}) : {error}"
