import logging
from contextvars import ContextVar

try:
    from google import genai
    from google.genai import types
except Exception as exc:  # pragma: no cover - environment-dependent import
    genai = None
    types = None
    _GENAI_IMPORT_ERROR = exc
else:
    _GENAI_IMPORT_ERROR = None

from app.services.chart_spec import CONSIGNE_EMIT_CHART, CONSIGNE_TRANSFORMATION
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


def complete_text(prompt: str, model: str, history: list | None = None,
                  system: str | None = None) -> str:
    """Point d'entrée unique multi-fournisseur pour un prompt.
    Route vers Gemini / Mistral / OpenAI / Groq / Anthropic / Ollama selon le format de `model`.
    Convention : "<provider>/<model>" pour les fournisseurs API (ex: "openai/gpt-4o-mini"),
    nom nu préfixé "gemini" pour Gemini, sinon un modèle Ollama local (ex: "gemma2:latest").

    `system` est remis à chaque fournisseur dans SON emplacement dédié —
    `system_instruction` chez Gemini, message de rôle `system` en OpenAI-compatible,
    champ `system` chez Anthropic et Ollama. C'est le seul canal que les modèles
    traitent comme une consigne à respecter ; concaténé en tête du tour utilisateur
    il n'est qu'un préambule parmi d'autres, que les petits modèles paraphrasent ou
    ignorent. Laisser `system` à None reproduit le comportement d'un prompt de tâche
    nu (classification d'intention, génération de code…), qui n'a pas de consigne
    conversationnelle à porter.
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
        elif provider == "custom":
            from app.services.custom_provider_service import complete as provider_complete
        else:
            provider_complete = None
        if provider_complete is not None:
            return provider_complete(prompt, real_model, history=history, system=system).strip()

    if not model or model.startswith("gemini"):
        # `get_gemini_client` d'abord : il lève l'erreur explicite « clé manquante »
        # et garantit que `types` a bien été importé avant qu'on s'en serve.
        client = get_gemini_client()
        gemini_history = _build_gemini_history(history)
        chat = client.chats.create(
            model=model,
            history=gemini_history,
            # Posé sur la session de chat plutôt que sur l'envoi : le SDK le
            # conserve et le réapplique à chaque `send_message` ultérieur.
            config=types.GenerateContentConfig(system_instruction=system) if system else None,
        )
        return chat.send_message(prompt).text.strip()

    full_prompt = ""
    for msg in history[-5:]:
        role = "User" if msg["role"] == "user" else "Assistant"
        full_prompt += f"{role}: {msg['content']}\n"
    full_prompt += prompt
    return ask_ollama(full_prompt, model=model, system=system).strip()


# ── Langue de réponse de l'agent ─────────────────────────────────────────────
# L'application répond en français ; seules les campagnes d'évaluation ont
# besoin d'autre chose (InfiAgent-DABench pose ses questions en anglais, et une
# consigne de langue au niveau du message utilisateur se ferait écraser par la
# règle du prompt système).
#
# Un ContextVar plutôt qu'un paramètre de fonction : la réponse finale peut
# sortir de n'importe laquelle des branches de `_run_chat` (sandbox, séries
# temporelles, tournoi supervisé…), qui appellent `ask_gemini` à des profondeurs
# très différentes. `asyncio.to_thread` recopie le contexte courant, la valeur
# traverse donc les bascules de thread du chemin de chat.
response_language: ContextVar[str] = ContextVar("response_language", default="fr")

# Deux prompts complets plutôt qu'une ligne de consigne insérée dans un texte
# français : mesuré, une phrase « answer in English » noyée dans des
# instructions françaises est ignorée par le modèle, qui suit la langue
# dominante du prompt. La variante anglaise doit l'être de bout en bout.
_SYSTEM_PROMPTS = {
    "fr": """Tu es un agent d'analyse de données. Tu es proactif, clair et accessible.
Tu interprètes toujours les résultats en langage naturel.
Quand des données sont disponibles en contexte, tu t'appuies dessus pour répondre.
Tu réponds toujours en français.

Ne commence JAMAIS tes réponses par des formules d'introduction ou des salutations clichées/répétitives (par exemple : "Bonjour", "En tant qu'expert en analyse de données, voici...", "En tant qu'agent...", "Voici le résultat de...", "En tant que grand modèle de langue...", etc.). Entre directement dans le sujet ou réponds directement à la question sans préambule inutile.

À CHAQUE RÉPONSE, tu DOIS toujours formuler 1 à 3 suggestions d'analyses complémentaires pertinentes que l'utilisateur pourrait te demander de faire sur le jeu de données pour approfondir le sujet.""",

    # Variante d'évaluation : pas de suggestions d'analyses complémentaires
    # imposées — sur un banc en forme fermée, elles n'ajoutent que du bruit
    # autour de la réponse attendue.
    "en": """You are a data analysis agent. You are proactive, clear and accessible.
You always interpret results in natural language.
When data is available in the context, you rely on it to answer.
You always answer in English.

NEVER begin your answers with introductory or clichéd greetings (for example: "Hello", "As a data analysis expert, here is...", "As an agent...", "Here is the result of...", etc.). Get straight to the point and answer the question directly.

When the user asks for a specific answer format, follow it EXACTLY and put nothing before it.""",
}


def language_rule(default: str = "fr") -> str:
    """Consigne de langue seule, pour les prompts construits ailleurs."""
    rules = {"fr": "Réponds en français.", "en": "Answer in English."}
    return rules.get(response_language.get(), rules[default])


def build_system_prompt() -> str:
    return _SYSTEM_PROMPTS.get(response_language.get(), _SYSTEM_PROMPTS["fr"])

def ask_gemini(prompt: str, history: list = [], data_context: str = "", model: str | None = None) -> str:
    """Réponse conversationnelle de l'agent, prompt système compris.

    Le tour utilisateur ne porte plus que ce qui relève de l'utilisateur — les
    données en contexte et sa question. Le prompt système part dans l'emplacement
    dédié du fournisseur (voir `complete_text`). Concaténé comme avant, il se
    présentait au modèle comme un texte à commenter au même titre que le reste, et
    chez Ollama il pouvait tomber dans la zone amputée par le raccourcissement du
    prompt : les consignes de langue et de style disparaissaient alors sans trace.

    Renvoie le message d'erreur au lieu de le lever : les appelants (chat, rapports)
    l'affichent tel quel à l'utilisateur.
    """
    model = model or config.get_default_model()
    question = f"{data_context}\n\n" if data_context else ""
    question += f"Question : {prompt}"
    try:
        logger.debug("Envoyer requête LLM — model=%s prompt_len=%d history_len=%d", model, len(question), len(history))
        response = complete_text(question, model, history, system=build_system_prompt())
        logger.debug("Réponse LLM reçue (len=%d)", len(response or ""))
        return response
    except Exception as e:
        logger.exception("Erreur lors de l'appel au modèle %s : %s", model, str(e))
        return f"Erreur Gemini : {str(e)}"


def ask_gemini_vision(prompt: str, images: list, history: list = [], model: str | None = None,
                      system: str | None = None) -> str:
    """Répond à une question en s'appuyant directement sur des images (ex: pages de
    document scanné) — utilisé notamment par la transcription OCR, 2e recours de
    la cascade de `ocr_service`.

    Ne pas appeler directement : passer par `vision_service.ask_vision`, qui route
    vers le fournisseur choisi par l'utilisateur ET fournit `system`. Cette fonction
    n'est que le bras Gemini de ce routage."""
    try:
        # Avant de toucher à `types` : si l'import du SDK a échoué, cet appel lève
        # l'erreur explicite plutôt qu'un AttributeError sur un module à None.
        client = get_gemini_client()
        gemini_history = _build_gemini_history(history)

        parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images]
        parts.append(types.Part.from_text(text=f"Question : {prompt}"))

        chat = client.chats.create(
            model=model or config.get_default_model(),
            history=gemini_history,
            config=types.GenerateContentConfig(system_instruction=system) if system else None,
        )
        response = chat.send_message(parts)
        return response.text
    except Exception as e:
        logger.exception("Erreur lors de l'appel vision à Gemini : %s", str(e))
        return f"Erreur Gemini (vision) : {str(e)}"


def generate_visualization_code(question: str, data_context: str, history: list = [], model: str | None = None) -> str:
    """
    Demande à Gemini de générer uniquement du code Python
    pour répondre à une question de visualisation.
    """
    model = model or config.get_default_model()
    prompt = f"""
Tu es un expert en analyse de données Python.

{data_context}

Question : {question}

Génère UNIQUEMENT du code Python exécutable pour répondre à cette question.
Le dataframe est déjà chargé dans la variable `df`.

{CONSIGNE_EMIT_CHART}


Ne mets aucun commentaire, aucune explication, aucun bloc markdown.
Juste le code Python pur, directement exécutable.
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

        return _sans_balises_markdown(code)
    except Exception as e:
        return ""


def generate_transformation_code(question: str, data_context: str, history: list = [],
                                 model: str | None = None) -> str:
    """Code Python qui MODIFIE le jeu de données de la session.

    Contrairement aux autres générateurs, le code produit ici a un effet
    persistant : sa sortie remplace les données de l'utilisateur. L'état
    précédent est archivé côté serveur, donc la modification reste réversible.
    """
    model = model or config.get_default_model()
    prompt = f"""
Tu es un expert en manipulation de données avec pandas.

{data_context}

Modification demandée : {question}

{CONSIGNE_TRANSFORMATION}

{language_rule()}
Ne mets aucun commentaire, aucune explication, aucun bloc markdown.
Juste le code Python pur, directement exécutable.
"""
    try:
        if model and not model.startswith("gemini"):
            code = complete_text(prompt, model, history).strip()
        else:
            client = get_gemini_client()
            chat = client.chats.create(model=model, history=_build_gemini_history(history))
            code = chat.send_message(prompt).text.strip()
        return _sans_balises_markdown(code)
    except Exception:
        logger.exception("Génération du code de transformation impossible.")
        return ""


def _sans_balises_markdown(code: str) -> str:
    """Retire la clôture ```python … ``` que les modèles ajoutent malgré la consigne."""
    if not code.startswith("```"):
        return code
    lines = code.split("\n")
    if lines[-1].startswith("```"):
        return "\n".join(lines[1:-1])
    return "\n".join(lines[1:])


def generate_stats_code(question: str, data_context: str, history: list = [], model: str | None = None) -> str:
    """Code Python qui CALCULE une statistique descriptive demandée en chat.

    Ce chemin passait auparavant par PandasAI, qui exécutait son code dans le
    processus backend et, en cas d'échec, laissait le modèle répondre de
    mémoire — un chiffre inventé s'y présentait comme un chiffre calculé. Le
    code produit ici part dans le même sandbox isolé que les autres intentions.
    """
    model = model or config.get_default_model()
    prompt = f"""
Tu es un analyste de données Python.

{data_context}

Question : {question}

Génère UNIQUEMENT du code Python exécutable qui CALCULE la réponse à partir du
dataframe déjà chargé dans `df`. {language_rule()}

RÈGLE ABSOLUE : aucune valeur affichée ne doit être écrite en dur. Toute
statistique montrée sort d'un calcul sur `df` — c'est la raison d'être de ce
code, l'utilisateur ne verra pas les données autrement.

Mise en forme du résultat :
- Un tableau : arrondis (`.round(2)`) puis `print(markdown_table(tableau))`.
- Une valeur unique : `print` avec son libellé et son unité.
- Ne montre que ce qui répond à la question : pas de `describe()` complet quand
  une seule statistique est demandée.
- Au-delà de 30 lignes, n'affiche que les 30 premières et indique le total.
- Les valeurs manquantes sont exclues des calculs, et leur nombre est signalé
  quand il n'est pas nul — une moyenne calculée sur des trous n'est pas la même
  statistique.

{CONSIGNE_EMIT_CHART}

Ajoute un graphique seulement quand il éclaire la réponse (distribution,
fréquences des principales modalités, corrélations) ; une valeur unique se lit
mieux en texte.

Ne mets aucun commentaire, aucune explication, aucun bloc markdown.
Juste le code Python pur, directement exécutable.
"""
    try:
        if model and not model.startswith("gemini"):
            code = complete_text(prompt, model, history).strip()
        else:
            client = get_gemini_client()
            chat = client.chats.create(model=model, history=_build_gemini_history(history))
            code = chat.send_message(prompt).text.strip()
        return _sans_balises_markdown(code)
    except Exception:
        logger.exception("Génération du code de statistiques descriptives impossible.")
        return ""