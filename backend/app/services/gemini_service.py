import logging
from google import genai
from google.genai import types
from app.services.ollama_service import ask_ollama
from app.core.config import GEMINI_API_KEY

logger = logging.getLogger("app.gemini")

_client = None

def get_gemini_client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_GEMINI_API_KEY_HERE":
            logger.error("GEMINI_API_KEY non configurée ou invalide. Vérifiez backend/.env ou la variable d'environnement.")
            raise ValueError("Clé API Gemini manquante. Veuillez configurer GEMINI_API_KEY dans le fichier .env.")
        try:
            _client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("Client Gemini initialisé avec succès.")
        except Exception:
            logger.exception("Échec lors de l'initialisation du client Gemini.")
            raise
    return _client


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

        gemini_history = []
        for msg in history[-10:]:  # garde les 10 derniers échanges
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])]
                )
            )

        if model and not model.startswith("gemini"):
            # Route vers Ollama
            ollama_prompt = f"{full_prompt}\n\nHistorique récent:\n"
            for msg in history[-5:]:
                role = "User" if msg["role"] == "user" else "Assistant"
                ollama_prompt += f"{role}: {msg['content']}\n"
            return ask_ollama(ollama_prompt, model=model)

        client = get_gemini_client()
        logger.debug("Envoyer requête Gemini — model=%s prompt_len=%d history_len=%d", model, len(full_prompt), len(gemini_history))
        chat = client.chats.create(model=model, history=gemini_history)
        response = chat.send_message(full_prompt)
        logger.debug("Réponse Gemini reçue (len=%d)", len(response.text) if getattr(response, 'text', None) else 0)
        return response.text
    except Exception as e:
        logger.exception("Erreur lors de l'appel à Gemini : %s", str(e))
        return f"Erreur Gemini : {str(e)}"


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
        gemini_history = []
        for msg in history[-10:]:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])]
                )
            )

        if model and not model.startswith("gemini"):
            # Route vers Ollama
            ollama_prompt = f"{prompt}\n\nHistorique récent:\n"
            for msg in history[-5:]:
                role = "User" if msg["role"] == "user" else "Assistant"
                ollama_prompt += f"{role}: {msg['content']}\n"
            code = ask_ollama(ollama_prompt, model=model).strip()
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