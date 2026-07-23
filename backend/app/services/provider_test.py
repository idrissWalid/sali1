"""Vérifie qu'une clé API fournisseur + modèle fonctionnent avant enregistrement,
via une requête minimale (peu de tokens), sans jamais persister la clé testée.
"""


def verify_provider_key(provider: str, model: str, api_key: str) -> None:
    """Lève une exception explicite si la clé/modèle est invalide."""
    if provider == "gemini":
        _verify_gemini(model, api_key)
    elif provider == "anthropic":
        from app.services.anthropic_service import complete
        complete("Test", model, api_key=api_key, max_tokens=5)
    elif provider == "openai":
        from app.services.openai_service import BASE_URL
        from app.services.openai_compatible import complete
        complete(BASE_URL, api_key, model, "Test", max_tokens=5, label="OpenAI")
    elif provider == "groq":
        from app.services.groq_service import BASE_URL
        from app.services.openai_compatible import complete
        complete(BASE_URL, api_key, model, "Test", max_tokens=5, label="Groq")
    elif provider == "mistral":
        from app.services.mistral_service import BASE_URL
        from app.services.openai_compatible import complete
        complete(BASE_URL, api_key, model, "Test", max_tokens=5, label="Mistral")
    else:
        raise ValueError(f"Fournisseur inconnu : {provider}")


def _verify_gemini(model: str, api_key: str) -> None:
    try:
        from google import genai
        from google.genai import types
    except Exception as exc:  # pragma: no cover - environment-dependent import
        raise RuntimeError(f"Google GenAI indisponible : {exc}") from exc

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=15000))
    client.models.generate_content(
        model=model,
        contents="Test",
        config=types.GenerateContentConfig(max_output_tokens=5),
    )
