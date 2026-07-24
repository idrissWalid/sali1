import os
import logging
import requests

logger = logging.getLogger("app.ollama")

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
DEFAULT_OLLAMA_MODEL = os.getenv("DEFAULT_OLLAMA_MODEL", "gemma2:latest")
# Une limite basse évite de demander au serveur local de réserver un contexte
# disproportionné lorsqu'un profil de données et l'historique sont combinés.
MAX_PROMPT_CHARS = int(os.getenv("OLLAMA_MAX_PROMPT_CHARS", "16000"))
# Nombre de couches déchargées sur le GPU.
#   "auto" (défaut) : on n'envoie pas `num_gpu` et Ollama décide seul du nombre
#                     maximal de couches qui tiennent en VRAM. C'est le réglage
#                     qui exploite le GPU sans le brider artificiellement.
#   "-1"            : force le déchargement de TOUTES les couches. À éviter ici :
#                     gemma2 (9 Md) + un contexte de 4096 dépassent la VRAM de la
#                     carte et Ollama renvoie une erreur d'allocation Vulkan.
#   un entier       : nombre de couches imposé (0 = CPU uniquement).
_num_gpu_setting = os.getenv("OLLAMA_NUM_GPU", "auto").strip().lower()
OLLAMA_NUM_GPU = None if _num_gpu_setting in ("", "auto") else int(_num_gpu_setting)
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


def _generate(model: str, prompt: str, num_ctx: int, num_predict: int, num_gpu: int | None = -999) -> str:
    """Un appel Ollama. `num_gpu` vaut par défaut le réglage global ; passer une
    valeur explicite (0 = CPU) permet de rejouer la requête en mode dégradé."""
    effective_num_gpu = OLLAMA_NUM_GPU if num_gpu == -999 else num_gpu

    options = {"num_ctx": num_ctx, "num_predict": num_predict}
    if effective_num_gpu is not None:
        options["num_gpu"] = effective_num_gpu

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "5m",
        # Sans cela, les modèles « thinking » (qwen3.x…) consomment tout leur
        # budget de tokens en raisonnement et renvoient un `response` vide, le
        # contenu partant dans le champ `thinking`. Les modèles classiques
        # ignorent ce paramètre sans erreur.
        "think": False,
        "options": options,
    }
    logger.debug("Ollama request: model=%s num_ctx=%d num_predict=%d num_gpu=%s prompt_len=%d", model, num_ctx, num_predict, effective_num_gpu, len(prompt))
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=180)
        logger.debug("Ollama HTTP %s response (truncated 1000 chars): %s", response.status_code, response.text[:1000])
        response.raise_for_status()
        data = response.json()
        text = data.get("response") or ""
        if not text.strip():
            # Filet de sécurité si un modèle ignore `think: False`.
            text = data.get("thinking") or ""
        return text
    except requests.RequestException as e:
        logger.exception("Erreur lors de l'appel à Ollama: %s", str(e))
        raise


def _error_detail(error: Exception) -> str:
    response = getattr(error, "response", None)
    if response is not None:
        return response.text[:500]
    return str(error)


def ask_ollama(prompt: str, model: str | None = None) -> str:
    """Interroge Ollama en dégradant progressivement en cas d'échec.

    Sur une machine dont le GPU ne peut pas accueillir le modèle demandé, Ollama
    échoue soit par un HTTP 500 d'allocation, soit en tuant llama-server
    (connexion coupée). On rejoue alors la requête sur le CPU avec le MÊME
    modèle — ce qui préserve le choix de l'utilisateur — avant d'envisager un
    modèle de secours plus petit.
    """
    selected_model = (model or DEFAULT_OLLAMA_MODEL).strip()
    safe_prompt = _trim_prompt(prompt)

    # 1. Réglage nominal (GPU non bridé si OLLAMA_NUM_GPU=auto).
    try:
        return _generate(selected_model, safe_prompt, num_ctx=4096, num_predict=512)
    except requests.RequestException as error:
        last_error = error
        logger.warning("Ollama : échec nominal pour %s (%s).", selected_model, _error_detail(error)[:200])

    # 2. Même modèle, forcé sur CPU.
    try:
        logger.warning("Ollama : repli CPU pour %s.", selected_model)
        return _generate(selected_model, safe_prompt, num_ctx=4096, num_predict=512, num_gpu=0)
    except requests.RequestException as error:
        last_error = error

    # 3. Même modèle, CPU et contexte réduit (machines à faible RAM).
    try:
        return _generate(
            selected_model,
            _trim_prompt(safe_prompt, limit=7500),
            num_ctx=2048,
            num_predict=384,
            num_gpu=0,
        )
    except requests.RequestException as error:
        last_error = error

    # 4. Dernier recours : modèles de secours plus légers.
    for fallback_model in FALLBACK_MODELS:
        if fallback_model == selected_model:
            continue
        try:
            logger.warning("Ollama : bascule sur le modèle de secours %s.", fallback_model)
            return _generate(
                fallback_model,
                _trim_prompt(safe_prompt, limit=7500),
                num_ctx=2048,
                num_predict=384,
                num_gpu=0,
            )
        except requests.RequestException:
            continue

    return f"Erreur Ollama ({selected_model}) : {_error_detail(last_error)}"
