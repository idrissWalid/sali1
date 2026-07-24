from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import json
from app.services.gemini_service import ask_gemini, generate_visualization_code
from app.services.ml_service import generate_ml_code, generate_ml_interpretation, detect_model_family
from app.services.model_specs import MODEL_SPECS
from app.services.intent_service import detect_intent
from app.services.code_pipeline import run_with_autocorrect
from app.services.session_service import (
    get_session, add_to_history, get_history,
    get_data_context, get_session_type,
    get_file_bytes, save_message_to_report,
    get_embedded_table_context, get_embedded_table
)

router = APIRouter()

DATASET_INTENTS = ("stat_descriptive", "series_temporelles", "visualisation", "ml", "analyse")

class ChatRequest(BaseModel):
    session_id: str
    message: str
    model: Optional[str] = "gemma2:latest"

class ChatResponse(BaseModel):
    response: str
    session_id: str
    images: Optional[List[str]] = []
    sources: Optional[List[dict]] = []


def _step(phase: str, message: str) -> dict:
    """Étape de travail annoncée au client pendant qu'il patiente.

    `phase` sert de clé stable au frontend (icône, couleur), `message` est le
    libellé affiché.
    """
    return {"type": "step", "phase": phase, "message": message}


async def _run_dataset_intent(intent, session_id, message, model, history, file_bytes, filename, data_context):
    """Exécute l'intention détectée (pandasai / timecopilot / sandbox de code)
    sur un dataset — qu'il s'agisse du fichier principal d'une session tabulaire
    ou d'un tableau attaché à une session document.

    Générateur : émet des étapes puis un unique événement `result`.
    """
    images = []

    if intent == "rapport":
        yield {
            "type": "result",
            "response": (
                "Votre rapport est prêt à être généré. "
                "Cliquez sur **Rapport PDF** ou **Rapport Word** "
                "dans le panneau Studio pour le télécharger."
            ),
            "images": images,
        }
        return

    # ── Statistiques descriptives via PandasAI ──
    if intent == "stat_descriptive":
        if file_bytes:
            from app.services.pandasai_service import ask_pandasai
            yield _step("compute", "Calcul des statistiques sur vos données…")
            result = ask_pandasai(file_bytes, filename, message, model=model)

            if result["error"]:
                yield _step("thinking", "Réflexion…")
                response = ask_gemini(prompt=message, history=history, data_context=data_context, model=model)
            else:
                images = result["images"]
                raw_output = result["output"]

                interp_prompt = f"""
{data_context}
L'utilisateur a demandé : {message}
Résultat de l'analyse statistique : {raw_output}
{"Un graphique a été généré." if images else ""}

Présente ce résultat de façon claire et accessible en français (2-4 phrases).
Ne répète pas les chiffres bruts si le résultat parle de lui-même — explique leur signification.
"""
                yield _step("interpreting", "Interprétation des résultats…")
                interpretation = ask_gemini(prompt=interp_prompt, history=history, model=model)
                response = f"{raw_output}\n\n---\n\n{interpretation}" if raw_output and raw_output != "Aucun résultat retourné." else interpretation
        else:
            yield _step("thinking", "Réflexion…")
            response = ask_gemini(prompt=message, history=history, data_context=data_context, model=model)
        yield {"type": "result", "response": response, "images": images}
        return

    # ── Séries temporelles via TimeCopilot ──
    if intent == "series_temporelles":
        if file_bytes:
            from app.services.timeseries_service import ask_timecopilot
            yield _step("compute", "Analyse de la série temporelle…")
            result = ask_timecopilot(file_bytes, filename, message)

            if result["error"]:
                yield _step("thinking", "Réflexion…")
                response = ask_gemini(prompt=message, history=history, data_context=data_context, model=model)
            else:
                images = result.get("images", [])
                raw_output = result["output"]

                interp_prompt = f"""
{data_context}
L'utilisateur a demandé : {message}
Résultat de l'analyse de séries temporelles : {raw_output}

Présente ce résultat de façon claire et accessible en français (2-4 phrases).
Explique les tendances temporelles ou les prévisions identifiées.
"""
                yield _step("interpreting", "Interprétation des résultats…")
                interpretation = ask_gemini(prompt=interp_prompt, history=history, model=model)
                response = f"{raw_output}\n\n---\n\n{interpretation}" if raw_output and raw_output != "Aucun résultat retourné." else interpretation
        else:
            yield _step("thinking", "Réflexion…")
            response = ask_gemini(prompt=message, history=history, data_context=data_context, model=model)
        yield {"type": "result", "response": response, "images": images}
        return

    if intent in ("visualisation", "ml", "analyse"):
        spec = None
        if intent == "visualisation":
            yield _step("coding", "Génération du code du graphique…")
            code = generate_visualization_code(message, data_context, history, model=model)
        elif intent == "ml":
            yield _step("thinking", "Choix du type de modèle…")
            family = detect_model_family(message, model)
            spec = MODEL_SPECS[family]
            yield _step("coding", f"Génération du code du modèle ({family})…")
            code = generate_ml_code(message, data_context, family, history, model)
        else:
            yield _step("coding", "Génération du code d'analyse…")
            code = generate_visualization_code(message, data_context, history, model=model)

        if code and file_bytes:
            yield _step(
                "executing",
                "Entraînement du modèle…" if intent == "ml" else "Exécution du code…",
            )
            result = run_with_autocorrect(
                initial_code=code,
                file_bytes=file_bytes,
                filename=filename,
                question=message,
                data_context=data_context,
                spec=spec,
                model=model,
            )

            if result["error"]:
                technical = result["error"]["technical"]
                simple = result["error"]["simple"]
                response = f"```\n{technical}\n```\n\nPour faire simple : {simple}"
            else:
                images = result["images"]
                models_data = result.get("models", [])
                if models_data:
                    from app.services.session_service import save_model_to_db
                    for m_data in models_data:
                        save_model_to_db(session_id, m_data)

                yield _step("interpreting", "Interprétation des résultats…")
                if intent == "ml":
                    metrics_str = str(result.get("metrics")) if result.get("metrics") else result.get("output", "")
                    response = generate_ml_interpretation(
                        message, metrics_str, data_context, len(images) > 0, history, model
                    )
                else:
                    interp_prompt = f"""
{data_context}
L'utilisateur a demandé : {message}
Sortie texte du code : {result['output'] or 'Aucune.'}
{"Un graphique a été généré." if images else ""}
Rédige une interprétation concise et claire en 2-4 phrases.
"""
                    response = ask_gemini(prompt=interp_prompt, history=history, model=model)
        else:
            yield _step("thinking", "Réflexion…")
            response = ask_gemini(prompt=message, history=history, data_context=data_context, model=model)
        yield {"type": "result", "response": response, "images": images}
        return

    # Conversation générale
    yield _step("thinking", "Réflexion…")
    response = ask_gemini(prompt=message, history=history, data_context=data_context, model=model)
    yield {"type": "result", "response": response, "images": images}


async def _run_chat(request: ChatRequest):
    """Déroulé complet d'un échange, sous forme d'étapes puis d'un `result`."""
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable ou expirée.")

    session_type = get_session_type(request.session_id)
    history = get_history(request.session_id)
    add_to_history(request.session_id, "user", request.message)

    images = []
    sources = []
    response = ""

    # ── Chemin B : documents ───────────────────────────────────
    if session_type == "document_visual":
        from app.services.colsmolvlm_service import retrieve_visual_pages
        from app.services.gemini_service import ask_gemini_vision

        yield _step("searching", "Recherche des pages pertinentes du document…")
        pages = retrieve_visual_pages(request.session_id, request.message)
        sources = [{"page": p["page"], "text": ""} for p in pages]
        prompt = f"""
Question : {request.message}
Réponds uniquement à partir des pages du document ci-jointes.
"""
        yield _step("reading", "Lecture des pages retrouvées…")
        response = ask_gemini_vision(prompt, [p["image_bytes"] for p in pages], history=history)

    elif session_type == "document":
        embedded_bytes, embedded_filename, _, _ = get_embedded_table(request.session_id)

        # Un tableau est attaché à ce document (rapport PDF...) : si la question
        # est de nature quantitative, on la route vers le même pipeline pandasai
        # / sandbox qu'une vraie session tabulaire plutôt que la simple lecture
        # narrative du résumé RAG.
        intent = None
        if embedded_bytes:
            yield _step("thinking", "Analyse de votre question…")
            intent = detect_intent(request.message, request.model)

        if embedded_bytes and intent in DATASET_INTENTS:
            table_context = get_embedded_table_context(request.session_id)
            async for event in _run_dataset_intent(
                intent, request.session_id, request.message, request.model, history,
                embedded_bytes, embedded_filename, table_context
            ):
                if event["type"] == "result":
                    response, images = event["response"], event["images"]
                else:
                    yield event
        else:
            from app.services.rag_service import retrieve_context_with_sources
            yield _step("searching", "Recherche des passages pertinents…")
            context, sources = retrieve_context_with_sources(request.session_id, request.message)
            table_context = get_embedded_table_context(request.session_id)
            prompt = f"""
Extraits du document pertinents (numérotés) :
{context}
{table_context}
Question : {request.message}
Réponds uniquement à partir du document{" et du tableau de données ci-dessus" if table_context else ""}.

Après chaque affirmation qui s'appuie sur un extrait ci-dessus, ajoute immédiatement sa référence entre crochets (ex: [1]), en utilisant le numéro de l'extrait correspondant [Source N]. Si une affirmation combine plusieurs extraits, répète les crochets (ex: [1][2]). N'invente jamais de numéro qui ne correspond à aucun extrait fourni, et n'ajoute pas de liste de sources séparée à la fin : les références doivent être insérées directement dans le texte, au fil de la réponse.
"""
            yield _step("writing", "Rédaction de la réponse…")
            response = ask_gemini(prompt=prompt, history=history, model=request.model)

    # ── Chemin A : données tabulaires ─────────────────────────
    else:
        data_context = get_data_context(request.session_id)
        file_bytes, filename = get_file_bytes(request.session_id)
        yield _step("thinking", "Analyse de votre question…")
        intent = detect_intent(request.message, request.model)
        async for event in _run_dataset_intent(
            intent, request.session_id, request.message, request.model, history,
            file_bytes, filename, data_context
        ):
            if event["type"] == "result":
                response, images = event["response"], event["images"]
            else:
                yield event

    add_to_history(request.session_id, "model", response)
    save_message_to_report(request.session_id, "assistant", response, images, sources)

    yield {
        "type": "result",
        "response": response,
        "session_id": request.session_id,
        "images": images,
        "sources": sources,
    }


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Même traitement que /chat, mais les étapes intermédiaires sont poussées
    au fil de l'eau (NDJSON) pour que l'interface affiche l'activité en cours."""
    async def event_generator():
        try:
            async for event in _run_chat(request):
                yield json.dumps(event, ensure_ascii=False) + "\n"
                # Laisse la boucle d'événements écrire la ligne avant que
                # l'étape suivante ne monopolise le thread.
                await asyncio.sleep(0)
        except HTTPException as exc:
            yield json.dumps({"type": "error", "message": exc.detail}, ensure_ascii=False) + "\n"
        except Exception as exc:  # pragma: no cover - filet de sécurité
            yield json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Réponse en un seul bloc (les clients existants restent inchangés)."""
    final = None
    async for event in _run_chat(request):
        if event["type"] == "result":
            final = event

    if final is None:
        raise HTTPException(status_code=500, detail="Aucune réponse générée.")

    return ChatResponse(
        response=final["response"],
        session_id=request.session_id,
        images=final.get("images", []),
        sources=final.get("sources", []),
    )
