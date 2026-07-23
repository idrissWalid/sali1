from app.core.config import get_api_key
from app.services.openai_compatible import complete as _complete

BASE_URL = "https://api.groq.com/openai/v1"


def complete(prompt: str, model: str, history: list | None = None, system: str | None = None) -> str:
    return _complete(BASE_URL, get_api_key("groq"), model, prompt, history=history, system=system, label="Groq")
