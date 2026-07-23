import logging
import requests

logger = logging.getLogger("app.openai_compatible")


def _to_openai_messages(history: list, system: str | None, prompt: str) -> list:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    for msg in (history or [])[-10:]:
        role = "assistant" if msg["role"] in ("model", "assistant") else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": prompt})
    return messages


def complete(base_url: str, api_key: str, model: str, prompt: str,
             history: list | None = None, system: str | None = None,
             label: str = "API", max_tokens: int | None = None) -> str:
    if not api_key:
        raise ValueError(f"Clé API {label} manquante. Configurez-la dans les paramètres.")

    payload = {
        "model": model,
        "messages": _to_openai_messages(history, system, prompt),
        "temperature": 0.3,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]
