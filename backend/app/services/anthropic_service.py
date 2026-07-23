import requests
from app.core.config import get_api_key

BASE_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def complete(prompt: str, model: str, history: list | None = None, system: str | None = None,
             api_key: str | None = None, max_tokens: int = 2048) -> str:
    api_key = api_key or get_api_key("anthropic")
    if not api_key:
        raise ValueError("Clé API Anthropic manquante. Configurez-la dans les paramètres.")

    messages = []
    for msg in (history or [])[-10:]:
        role = "assistant" if msg["role"] in ("model", "assistant") else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        payload["system"] = system

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }
    response = requests.post(BASE_URL, json=payload, headers=headers, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["content"][0]["text"]
