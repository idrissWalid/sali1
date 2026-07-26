from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import json

def to_thread(func, /, *args, **kwargs):
    """Raccourci vers asyncio.to_thread : tous les appels LLM/pandas/sandbox de
    ce module sont synchrones et bloqueraient sinon la boucle d'événements pour
    toutes les autres sessions pendant toute leur durée (jusqu'à 180s pour un
    tournoi ML ou un grid search SARIMA)."""
    return asyncio.to_thread(func, *args, **kwargs)
from app.services.gemini_service import ask_gemini, generate_visualization_code
from app.services.ml_service import generate_ml_code, generate_ml_interpretation, detect_model_family
from app.services.model_specs import MODEL_SPECS, ModelFamily
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

# Familles supervisées : la cible est connue, plusieurs modèles peuvent donc être
# mis en concurrence et départagés sur des métriques comparables. Clustering et
# analyse factorielle en sont exclus — sans cible, il n'y a rien à départager.
_FAMILLES_SUPERVISEES = {
    ModelFamily.LINEAR_REGRESSION,
    ModelFamily.LOGISTIC_REGRESSION,
    ModelFamily.TREE_ENSEMBLE,
}

class ChatRequest(BaseModel):
    session_id: str
    message: str
    model: Optional[str] = None

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
    """Exécute l'intention détectée (pandasai / séries temporelles / sandbox de code)
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
            result = await to_thread(ask_pandasai, file_bytes, filename, message, model=model)

            if result["error"]:
                yield _step("thinking", "Réflexion…")
                response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
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
                interpretation = await to_thread(ask_gemini, prompt=interp_prompt, history=history, model=model)
                response = f"{raw_output}\n\n---\n\n{interpretation}" if raw_output and raw_output != "Aucun résultat retourné." else interpretation
        else:
            yield _step("thinking", "Réflexion…")
            response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
        yield {"type": "result", "response": response, "images": images}
        return

    # ── Séries temporelles : pipeline rigoureux ARIMA/SARIMA (méthodologie A–H),
    #    repli sur le moteur de prévision automatique. Dans les deux cas un modèle
    #    est sauvegardé (dashboard). ──
    if intent == "series_temporelles":
        if file_bytes:
            from app.services.timeseries_pipeline import run_rigorous_timeseries, run_autoforecast_timeseries
            from app.services.timeseries_service import infer_series_columns

            # Signale au frontend qu'un modèle est en cours de génération
            # (placeholder animé dans « Éléments générés »).
            yield {"type": "step", "phase": "model_generating", "message": "Modélisation rigoureuse (ARIMA/SARIMA, stationnarité, gates)…"}
            ts = await to_thread(
                run_rigorous_timeseries,
                question=message,
                data_context=data_context,
                file_bytes=file_bytes,
                filename=filename,
                session_id=session_id,
                history=history,
                model=model,
            )

            if ts["ok"]:
                yield {"type": "result", "response": ts["response"], "images": ts["images"], "model_id": ts.get("model_id"), "model_type": "timeseries"}
                return

            # Repli : moteur de prévision automatique (également sauvegardé comme
            # modèle avec dashboard). En chat l'utilisateur n'a désigné aucune
            # colonne, on déduit donc la série de la structure du fichier.
            date_col, value_col = await to_thread(infer_series_columns, file_bytes, filename)
            if date_col and value_col:
                yield {"type": "step", "phase": "model_generating", "message": "Repli sur la prévision automatique…"}
                tc = await to_thread(
                    run_autoforecast_timeseries,
                    question=message,
                    file_bytes=file_bytes,
                    filename=filename,
                    session_id=session_id,
                    data_context=data_context,
                    history=history,
                    model=model,
                    date_col=date_col,
                    value_col=value_col,
                )
                if tc["ok"]:
                    yield {"type": "result", "response": tc["response"], "images": tc["images"], "model_id": tc.get("model_id"), "model_type": "timeseries"}
                    return

            yield _step("thinking", "Réflexion…")
            response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
        else:
            yield _step("thinking", "Réflexion…")
            response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
        yield {"type": "result", "response": response, "images": images}
        return

    if intent in ("visualisation", "ml", "analyse"):
        spec = None
        if intent == "visualisation":
            yield _step("coding", "Génération du code du graphique…")
            code = await to_thread(generate_visualization_code, message, data_context, history, model=model)
        elif intent == "ml":
            yield _step("thinking", "Choix du type de modèle…")
            family = await to_thread(detect_model_family, message, model)

            # Régression et classification passent par le tournoi supervisé :
            # tous les modèles de la famille sont mis en concurrence et le
            # meilleur est livré, sans que le LLM ne génère de code. Clustering
            # et analyse factorielle ne sont pas supervisés et gardent le
            # chemin historique.
            if family in _FAMILLES_SUPERVISEES:
                from app.services.supervised_pipeline import run_supervised_tournament

                yield {"type": "step", "phase": "model_generating",
                       "message": "Mise en concurrence des modèles…"}
                res = await to_thread(
                    run_supervised_tournament,
                    question=message, file_bytes=file_bytes, filename=filename,
                    session_id=session_id, data_context=data_context,
                    history=history, model=model,
                )
                if not res.get("ok"):
                    detail = res.get("technical") or ""
                    reponse = res.get("error", "Le tournoi a échoué.")
                    if detail:
                        reponse = f"{reponse}\n\n```\n{str(detail)[:800]}\n```"
                    yield {"type": "result", "response": reponse, "images": [], "sources": []}
                    return
                yield {"type": "result", "response": res["response"],
                       "images": res.get("images", []), "model_id": res.get("model_id"),
                       "model_type": "supervised"}
                return

            spec = MODEL_SPECS[family]
            # Signale le début de génération d'un modèle (placeholder animé).
            yield {"type": "step", "phase": "model_generating", "message": f"Génération du code du modèle ({family})…"}
            code = await to_thread(generate_ml_code, message, data_context, family, history, model)
        else:
            yield _step("coding", "Génération du code d'analyse…")
            code = await to_thread(generate_visualization_code, message, data_context, history, model=model)

        if code and file_bytes:
            yield _step(
                "executing",
                "Entraînement du modèle…" if intent == "ml" else "Exécution du code…",
            )
            result = await to_thread(
                run_with_autocorrect,
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

                yield _step("interpreting", "Interprétation des résultats…")
                if intent == "ml":
                    metrics_str = str(result.get("metrics")) if result.get("metrics") else result.get("output", "")
                    response = await to_thread(
                        generate_ml_interpretation,
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
                    response = await to_thread(ask_gemini, prompt=interp_prompt, history=history, model=model)

                # Générée avant la persistance pour être stockée avec le modèle :
                # sans ça elle ne vivait que dans la réponse du chat et disparaissait
                # dès que l'utilisateur rouvrait le modèle depuis son dashboard.
                saved_model_id = None
                if models_data:
                    from app.services.session_service import save_model_to_db
                    for m_data in models_data:
                        if intent == "ml":
                            m_data.setdefault("metadata", {}).setdefault("metrics", {})["interpretation"] = response
                        mid = save_model_to_db(session_id, m_data)
                        if mid and not saved_model_id:
                            saved_model_id = mid

                yield {"type": "result", "response": response, "images": images, "model_id": saved_model_id, "model_type": "ml" if saved_model_id else None}
                return
        else:
            yield _step("thinking", "Réflexion…")
            response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
        yield {"type": "result", "response": response, "images": images}
        return

    # Conversation générale
    yield _step("thinking", "Réflexion…")
    response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
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
        from app.services.vision_service import VisionNonSupportee, ask_vision

        yield _step("searching", "Recherche des pages pertinentes du document…")
        pages = await to_thread(retrieve_visual_pages, request.session_id, request.message)
        sources = [{"page": p["page"], "text": ""} for p in pages]
        prompt = f"""
Question : {request.message}
Réponds uniquement à partir des pages du document ci-jointes.
"""
        yield _step("reading", "Lecture des pages retrouvées…")
        try:
            # Route vers le modèle multimodal du fournisseur choisi. Si celui-ci
            # n'a pas de vision, on le dit — sans rerouter vers un autre
            # fournisseur, ce qui enverrait le document ailleurs que prévu.
            response = await to_thread(ask_vision, prompt, [p["image_bytes"] for p in pages],
                                        model=request.model, history=history)
        except VisionNonSupportee as exc:
            yield {"type": "result", "response": str(exc), "images": [], "sources": sources}
            return

    elif session_type == "document":
        embedded_bytes, embedded_filename, _, _ = get_embedded_table(request.session_id)

        # Un tableau est attaché à ce document (rapport PDF...) : si la question
        # est de nature quantitative, on la route vers le même pipeline pandasai
        # / sandbox qu'une vraie session tabulaire plutôt que la simple lecture
        # narrative du résumé RAG.
        intent = None
        if embedded_bytes:
            yield _step("thinking", "Analyse de votre question…")
            intent = await to_thread(detect_intent, request.message, request.model)

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
            context, sources = await to_thread(retrieve_context_with_sources, request.session_id, request.message)
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
            response = await to_thread(ask_gemini, prompt=prompt, history=history, model=request.model)

    # ── Chemin A : données tabulaires ─────────────────────────
    else:
        data_context = get_data_context(request.session_id)
        file_bytes, filename = get_file_bytes(request.session_id)
        yield _step("thinking", "Analyse de votre question…")
        intent = await to_thread(detect_intent, request.message, request.model)
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
