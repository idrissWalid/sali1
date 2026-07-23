from app.core.config import get_api_key
from app.services.openai_compatible import complete as _complete

BASE_URL = "https://api.openai.com/v1"


def complete(prompt: str, model: str, history: list | None = None, system: str | None = None) -> str:
    return _complete(BASE_URL, get_api_key("openai"), model, prompt, history=history, system=system, label="OpenAI")
