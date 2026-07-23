from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.services.gemini_service import ask_gemini, generate_visualization_code
from app.services.ml_service import generate_ml_code, generate_ml_interpretation, detect_model_family
from app.services.model_specs import MODEL_SPECS
from app.services.intent_service import detect_intent
from app.services.code_pipeline import run_with_autocorrect
from app.services.session_service import (
    get_session, add_to_history, get_history,
    get_data_context, get_session_type,
    get_file_bytes, save_message_to_report
)

router = APIRouter()

class ChatRequest(BaseModel):
    session_id: str
    message: str
    model: Optional[str] = "gemma2:latest"

class ChatResponse(BaseModel):
    response: str
    session_id: str
    images: Optional[List[str]] = []
    sources: Optional[List[dict]] = []

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable ou expirée.")

    session_type = get_session_type(request.session_id)
    history = get_history(request.session_id)
    add_to_history(request.session_id, "user", request.message)

    images = []

    sources = []

    # ── Chemin B : documents ───────────────────────────────────
    if session_type == "document_visual":
        from app.services.colsmolvlm_service import retrieve_visual_pages
        from app.services.gemini_service import ask_gemini_vision

        pages = retrieve_visual_pages(request.session_id, request.message)
        sources = [{"page": p["page"], "text": ""} for p in pages]
        prompt = f"""
Question : {request.message}
Réponds uniquement à partir des pages du document ci-jointes.
"""
        response = ask_gemini_vision(prompt, [p["image_bytes"] for p in pages], history=history)

    elif session_type == "document":
        from app.services.rag_service import retrieve_context_with_sources
        context, sources = retrieve_context_with_sources(request.session_id, request.message)
        prompt = f"""
Extraits du document pertinents (numérotés) :
{context}

Question : {request.message}
Réponds uniquement à partir du document.

Après chaque affirmation qui s'appuie sur un extrait ci-dessus, ajoute immédiatement sa référence entre crochets (ex: [1]), en utilisant le numéro de l'extrait correspondant [Source N]. Si une affirmation combine plusieurs extraits, répète les crochets (ex: [1][2]). N'invente jamais de numéro qui ne correspond à aucun extrait fourni, et n'ajoute pas de liste de sources séparée à la fin : les références doivent être insérées directement dans le texte, au fil de la réponse.
"""
        response = ask_gemini(prompt=prompt, history=history, model=request.model)

    # ── Chemin A : données tabulaires ─────────────────────────
    else:
        data_context = get_data_context(request.session_id)

        # Détection d'intention par LLM
        intent = detect_intent(request.message, request.model)

        if intent == "rapport":
            response = (
                "Votre rapport est prêt à être généré. "
                "Cliquez sur **Rapport PDF** ou **Rapport Word** "
                "dans le panneau Studio pour le télécharger."
            )

        # ── NOUVEAU : Statistiques descriptives via PandasAI ──
        elif intent == "stat_descriptive":
            file_bytes, filename = get_file_bytes(request.session_id)

            if file_bytes:
                from app.services.pandasai_service import ask_pandasai
                result = ask_pandasai(file_bytes, filename, request.message, model=request.model)

                if result["error"]:
                    # Fallback : Gemini répond avec le contexte stats
                    response = ask_gemini(
                        prompt=request.message,
                        history=history,
                        data_context=data_context,
                        model=request.model
                    )
                else:
                    images = result["images"]
                    raw_output = result["output"]

                    # Enrichir la réponse PandasAI avec une interprétation Gemini
                    interp_prompt = f"""
{data_context}
L'utilisateur a demandé : {request.message}
Résultat de l'analyse statistique : {raw_output}
{"Un graphique a été généré." if images else ""}

Présente ce résultat de façon claire et accessible en français (2-4 phrases).
Ne répète pas les chiffres bruts si le résultat parle de lui-même — explique leur signification.
"""
                    interpretation = ask_gemini(prompt=interp_prompt, history=history, model=request.model)
                    # Combiner résultat brut + interprétation
                    response = f"{raw_output}\n\n---\n\n{interpretation}" if raw_output and raw_output != "Aucun résultat retourné." else interpretation
            else:
                response = ask_gemini(
                    prompt=request.message,
                    history=history,
                    data_context=data_context,
                    model=request.model
                )

        # ── NOUVEAU : Séries temporelles via TimeCopilot ──
        elif intent == "series_temporelles":
            file_bytes, filename = get_file_bytes(request.session_id)

            if file_bytes:
                from app.services.timeseries_service import ask_timecopilot
                result = ask_timecopilot(file_bytes, filename, request.message)

                if result["error"]:
                    # Fallback : Gemini répond avec le contexte
                    response = ask_gemini(
                        prompt=request.message,
                        history=history,
                        data_context=data_context,
                        model=request.model
                    )
                else:
                    images = result.get("images", [])
                    raw_output = result["output"]

                    # Enrichir la réponse TimeCopilot avec une interprétation Gemini
                    interp_prompt = f"""
{data_context}
L'utilisateur a demandé : {request.message}
Résultat de l'analyse de séries temporelles : {raw_output}

Présente ce résultat de façon claire et accessible en français (2-4 phrases).
Explique les tendances temporelles ou les prévisions identifiées.
"""
                    interpretation = ask_gemini(prompt=interp_prompt, history=history, model=request.model)
                    response = f"{raw_output}\n\n---\n\n{interpretation}" if raw_output and raw_output != "Aucun résultat retourné." else interpretation
            else:
                response = ask_gemini(
                    prompt=request.message,
                    history=history,
                    data_context=data_context,
                    model=request.model
                )

        elif intent in ("visualisation", "ml", "analyse"):
            file_bytes, filename = get_file_bytes(request.session_id)

            # Générer le code selon l'intention
            spec = None
            if intent == "visualisation":
                code = generate_visualization_code(request.message, data_context, history, model=request.model)
            elif intent == "ml":
                family = detect_model_family(request.message, request.model)
                spec = MODEL_SPECS[family]
                code = generate_ml_code(request.message, data_context, family, history, request.model)
            else:
                # Analyse statistique avancée
                code = generate_visualization_code(request.message, data_context, history, model=request.model)

            if code and file_bytes:
                # Pipeline avec auto-correction → Docker sandbox
                result = run_with_autocorrect(
                    initial_code=code,
                    file_bytes=file_bytes,
                    filename=filename,
                    question=request.message,
                    data_context=data_context,
                    spec=spec,
                    model=request.model,
                )

                if result["error"]:
                    technical = result["error"]["technical"]
                    simple = result["error"]["simple"]
                    response = (
                        f"```\n{technical}\n```\n\n"
                        f"Pour faire simple : {simple}"
                    )
                else:
                    images = result["images"]
                    models_data = result.get("models", [])
                    if models_data:
                        from app.services.session_service import save_model_to_db
                        for m_data in models_data:
                            save_model_to_db(request.session_id, m_data)
                            
                    if intent == "ml":
                        metrics_str = str(result.get("metrics")) if result.get("metrics") else result.get("output", "")
                        response = generate_ml_interpretation(
                            request.message,
                            metrics_str,
                            data_context,
                            len(images) > 0,
                            history,
                            request.model
                        )
                    else:
                        interp_prompt = f"""
{data_context}
L'utilisateur a demandé : {request.message}
Sortie texte du code : {result['output'] or 'Aucune.'}
{"Un graphique a été généré." if images else ""}
Rédige une interprétation concise et claire en 2-4 phrases.
"""
                        response = ask_gemini(prompt=interp_prompt, history=history, model=request.model)
            else:
                response = ask_gemini(
                    prompt=request.message,
                    history=history,
                    data_context=data_context,
                    model=request.model
                )

        else:
            # Conversation générale
            response = ask_gemini(
                prompt=request.message,
                history=history,
                data_context=data_context,
                model=request.model
            )

    add_to_history(request.session_id, "model", response)
    save_message_to_report(request.session_id, "assistant", response, images, sources)

    return ChatResponse(
        response=response,
        session_id=request.session_id,
        images=images,
        sources=sources,
    )