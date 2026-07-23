import logging

try:
    from google import genai
    from google.genai import types
except Exception as exc:  # pragma: no cover - environment-dependent import
    genai = None
    types = None
    _GENAI_IMPORT_ERROR = exc
else:
    _GENAI_IMPORT_ERROR = None

from app.services.ollama_service import ask_ollama
from app.core import config

logger = logging.getLogger("app.gemini")


def _build_gemini_history(history: list) -> list:
    if types is None:
        return []
    gemini_history = []
    for msg in history[-10:]:
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg["content"])]
            )
        )
    return gemini_history


def get_gemini_client():
    if _GENAI_IMPORT_ERROR is not None:
        raise RuntimeError(f"Google GenAI indisponible : {_GENAI_IMPORT_ERROR}") from _GENAI_IMPORT_ERROR
    api_key = config.get_api_key("gemini")
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        logger.error("GEMINI_API_KEY non configurée ou invalide. Vérifiez backend/.env ou la variable d'environnement.")
        raise ValueError("Clé API Gemini manquante. Veuillez configurer GEMINI_API_KEY dans le fichier .env.")
    try:
        return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=30000))
    except Exception:
        logger.exception("Échec lors de l'initialisation du client Gemini.")
        raise


def complete_text(prompt: str, model: str, history: list | None = None) -> str:
    """Point d'entrée unique multi-fournisseur pour un prompt simple (sans le SYSTEM_PROMPT conversationnel).
    Route vers Gemini / Mistral / OpenAI / Groq / Anthropic / Ollama selon le format de `model`.
    Convention : "<provider>/<model>" pour les fournisseurs API (ex: "openai/gpt-4o-mini"),
    nom nu préfixé "gemini" pour Gemini, sinon un modèle Ollama local (ex: "gemma2:latest").
    """
    history = history or []

    if model and "/" in model:
        provider, real_model = model.split("/", 1)
        if provider == "mistral":
            from app.services.mistral_service import complete as provider_complete
        elif provider == "openai":
            from app.services.openai_service import complete as provider_complete
        elif provider == "groq":
            from app.services.groq_service import complete as provider_complete
        elif provider == "anthropic":
            from app.services.anthropic_service import complete as provider_complete
        else:
            provider_complete = None
        if provider_complete is not None:
            return provider_complete(prompt, real_model, history=history).strip()

    if not model or model.startswith("gemini"):
        client = get_gemini_client()
        gemini_history = _build_gemini_history(history)
        chat = client.chats.create(model=model, history=gemini_history)
        return chat.send_message(prompt).text.strip()

    full_prompt = ""
    for msg in history[-5:]:
        role = "User" if msg["role"] == "user" else "Assistant"
        full_prompt += f"{role}: {msg['content']}\n"
    full_prompt += prompt
    return ask_ollama(full_prompt, model=model).strip()


SYSTEM_PROMPT = """Tu es un agent d'analyse de données. Tu es proactif, clair et accessible.
Tu interprètes toujours les résultats en langage naturel.
Quand des données sont disponibles en contexte, tu t'appuies dessus pour répondre.
Tu réponds toujours en français.

Ne commence JAMAIS tes réponses par des formules d'introduction ou des salutations clichées/répétitives (par exemple : "Bonjour", "En tant qu'expert en analyse de données, voici...", "En tant qu'agent...", "Voici le résultat de...", "En tant que grand modèle de langue...", etc.). Entre directement dans le sujet ou réponds directement à la question sans préambule inutile.

À CHAQUE RÉPONSE, tu DOIS toujours formuler 1 à 3 suggestions d'analyses complémentaires pertinentes que l'utilisateur pourrait te demander de faire sur le jeu de données pour approfondir le sujet."""

def ask_gemini(prompt: str, history: list = [], data_context: str = "", model: str = "gemini-3.1-flash-lite-preview") -> str:
    try:
        full_prompt = SYSTEM_PROMPT
        if data_context:
            full_prompt += f"\n\n{data_context}"
        full_prompt += f"\n\nQuestion : {prompt}"

        gemini_history = _build_gemini_history(history)

        if model and not model.startswith("gemini"):
            # Route vers Mistral / OpenAI / Groq / Anthropic / Ollama
            return complete_text(full_prompt, model, history)

        client = get_gemini_client()
        logger.debug("Envoyer requête Gemini — model=%s prompt_len=%d history_len=%d", model, len(full_prompt), len(gemini_history))
        chat = client.chats.create(model=model, history=gemini_history)
        response = chat.send_message(full_prompt)
        logger.debug("Réponse Gemini reçue (len=%d)", len(response.text) if getattr(response, 'text', None) else 0)
        return response.text
    except Exception as e:
        logger.exception("Erreur lors de l'appel à Gemini : %s", str(e))
        return f"Erreur Gemini : {str(e)}"


def ask_gemini_vision(prompt: str, images: list, history: list = []) -> str:
    """Répond à une question en s'appuyant directement sur des images (ex: pages de
    document scanné retrouvées par ColSmolVLM) — pas de texte OCR intermédiaire.
    Nécessite un modèle Gemini (seul fournisseur multimodal câblé dans ce projet)."""
    try:
        full_prompt = SYSTEM_PROMPT + f"\n\nQuestion : {prompt}"
        gemini_history = _build_gemini_history(history)

        parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images]
        parts.append(types.Part.from_text(text=full_prompt))

        client = get_gemini_client()
        chat = client.chats.create(model="gemini-3.1-flash-lite-preview", history=gemini_history)
        response = chat.send_message(parts)
        return response.text
    except Exception as e:
        logger.exception("Erreur lors de l'appel vision à Gemini : %s", str(e))
        return f"Erreur Gemini (vision) : {str(e)}"


def generate_visualization_code(question: str, data_context: str, history: list = [], model: str = "gemini-3.1-flash-lite-preview") -> str:
    """
    Demande à Gemini de générer uniquement du code Python
    pour répondre à une question de visualisation.
    """
    prompt = f"""
Tu es un expert en analyse de données Python.

{data_context}

Question : {question}

Génère UNIQUEMENT du code Python exécutable pour répondre à cette question.
Le dataframe est déjà chargé dans la variable `df`.
Utilise matplotlib avec un style sombre :
  - fig, ax = plt.subplots(figsize=(10, 5))
  - fig.patch.set_facecolor('#1a1a1a')
  - ax.set_facecolor('#1a1a1a')
  - Couleurs de texte : '#e3e3e3'
  - Palette : ['#8ab4f8', '#c58af9', '#34a853', '#ea4335', '#fbbc04']

Ne mets aucun commentaire, aucune explication, aucun bloc markdown.
Juste le code Python pur, directement exécutable.

IMPORTANT: Lors de tes analyses visuelles, PRIVILÉGIE l'utilisation de courbes (graphiques linéaires, séries temporelles, courbes de tendance) pour montrer l'évolution et les résultats dès que les données s'y prêtent.
"""
    try:
        gemini_history = _build_gemini_history(history)

        if model and not model.startswith("gemini"):
            # Route vers Mistral / OpenAI / Groq / Anthropic / Ollama
            code = complete_text(prompt, model, history).strip()
        else:
            client = get_gemini_client()
            chat = client.chats.create(
                model=model,
                history=gemini_history
            )
            response = chat.send_message(prompt)
            code = response.text.strip()
            
        # Nettoyer si Gemini met des backticks malgré tout
        if code.startswith("```"):
            lines = code.split("\n")
            if lines[-1].startswith("```"):
                code = "\n".join(lines[1:-1])
            else:
                code = "\n".join(lines[1:])
        return code
    except Exception as e:
        return ""