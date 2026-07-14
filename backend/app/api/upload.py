from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
import json
import asyncio
from app.services.ingestion_service import detect_file_type, load_tabular
from app.services.analysis_service import analyze_tabular
from app.services.session_service import create_session, save_data_context, add_to_history
from app.services.session_service import save_file_bytes

router = APIRouter()

@router.get("/llm-models")
async def list_llm_models():
    try:
        import subprocess
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')[1:]
        models = [line.split()[0] for line in lines if line]
    except Exception:
        models = []
    # Set gemma as default if available
    gemma_model = "gemma2:latest" if "gemma2:latest" in models else ("gemma:2b" if "gemma:2b" in models else "gemma")
    if gemma_model in models:
        models.remove(gemma_model)
    models.insert(0, gemma_model)
    if "gemini-3.1-flash-lite-preview" not in models:
        models.append("gemini-3.1-flash-lite-preview")
    return {"models": models}

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), model: str = Form("gemma2:latest"), index_doc: str = Form("true")):
    async def event_generator():
        # Étape 1 : Lecture et détection du format
        yield json.dumps({
            "status": "processing",
            "step": 1,
            "message": "Lecture et détection du format du fichier..."
        }) + "\n"
        await asyncio.sleep(0.05)

        try:
            file_bytes = await file.read()
            filename = file.filename
            file_type = detect_file_type(filename)
        except Exception as e:
            yield json.dumps({
                "status": "error",
                "message": "Une erreur est survenue lors de la lecture du fichier.",
                "technical": str(e)
            }) + "\n"
            return

        if file_type == "unsupported":
            yield json.dumps({
                "status": "error",
                "message": "Format non supporté. Utilisez CSV, Excel ou PDF.",
                "technical": "Unsupported file format"
            }) + "\n"
            return

        if file_type == "tabular":
            # Étape 2 : Analyse structurelle
            yield json.dumps({
                "status": "processing",
                "step": 2,
                "message": "Analyse structurelle et calcul des statistiques..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                check = load_tabular(file_bytes, filename)
                if check["status"] == "error":
                    yield json.dumps({
                        "status": "error",
                        "message": "Votre fichier n'a pas pu être lu. Vérifiez qu'il n'est pas corrompu.",
                        "technical": check.get("message", "Error loading tabular data")
                    }) + "\n"
                    return

            except Exception as e:
                yield json.dumps({
                    "status": "error",
                    "message": "Erreur d'analyse des données tabulaires.",
                    "technical": str(e)
                }) + "\n"
                return

            # Étape 3 : Interprétation IA
            yield json.dumps({
                "status": "processing",
                "step": 3,
                "message": "Génération de l'interprétation intelligente par l'IA..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                result = await analyze_tabular(file_bytes, filename)
                if result.get("status") == "error":
                    yield json.dumps({
                        "status": "error",
                        "message": "Une erreur est survenue lors de l'analyse des données.",
                        "technical": result.get("message", "Unknown error in analysis")
                    }) + "\n"
                    return

                # Étape 4 : Initialisation de la session
                yield json.dumps({
                    "status": "processing",
                    "step": 4,
                    "message": "Finalisation et initialisation de la session..."
                }) + "\n"
                await asyncio.sleep(0.05)

                session_id = create_session()
                save_data_context(session_id, result["profile"], result["stats"], filename)
                from app.services.session_service import save_initial_analysis
                save_initial_analysis(session_id, result["interpretation"])
                save_file_bytes(session_id, file_bytes, filename)
                add_to_history(session_id, "model", result["interpretation"])

                # L'ancien dashboard HTML n'est plus généré ici.
                # Il sera généré à la volée en JSON par /api/dashboard/data/{session_id}

                yield json.dumps({
                    "status": "completed",
                    "data": {
                        "type": "tabular_analyzed",
                        "session_id": session_id,
                        "profile": result["profile"],
                        "stats": result["stats"],
                        "interpretation": result["interpretation"]
                    }
                }) + "\n"
            except Exception as e:
                yield json.dumps({
                    "status": "error",
                    "message": "Erreur lors du traitement IA ou de la création de session.",
                    "technical": str(e)
                }) + "\n"
                return

        if file_type == "document":
            from app.services.rag_service import index_document, summarize_document
            from app.services.gemini_service import ask_gemini
            from app.services.ollama_service import ask_ollama
            from app.services.session_service import set_session_type

            # Étape 2 : Découpage et Indexation
            yield json.dumps({
                "status": "processing",
                "step": 2,
                "message": "Découpage et indexation vectorielle du document..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                session_id = create_session()
                set_session_type(session_id, "document")
                
                if index_doc.lower() == "true":
                    index_result = index_document(session_id, file_bytes, filename)
                    if index_result["status"] == "error":
                        yield json.dumps({
                            "status": "error",
                            "message": "Le document n'a pas pu être indexé. Vérifiez qu'il contient du texte lisible.",
                            "technical": index_result.get("message", "Indexing error")
                        }) + "\n"
                        return
                    chunks_indexed = index_result["chunks_indexed"]
                else:
                    chunks_indexed = 0
            except Exception as e:
                yield json.dumps({
                    "status": "error",
                    "message": "Erreur lors de l'indexation du document.",
                    "technical": str(e)
                }) + "\n"
                return

            # Étape 3 : Analyse et résumé IA
            yield json.dumps({
                "status": "processing",
                "step": 3,
                "message": "Analyse et génération du résumé par l'IA..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                if index_doc.lower() == "true":
                    raw_context = summarize_document(session_id)
                else:
                    from app.services.rag_service import extract_text_from_pdf
                    full_text = extract_text_from_pdf(file_bytes)
                    raw_context = " ".join(full_text.split()[:2400]) # Prend environ le même nombre de mots que 6 chunks
                    
                summary_prompt = f"""
                Voici le début d'un document :

                {raw_context}

                Rédige un résumé structuré, naturel et fluide en français.
                Ne commence JAMAIS le résumé par une introduction ou des salutations (par exemple : "Bonjour", "En tant qu'expert...", "Voici le résumé..."). Rentre directement dans le vif du sujet.

                Organise ta réponse sous cette forme :

                ### 1. RÉSUMÉ
                [Rédige un paragraphe de 3 à 5 phrases résumant le contenu général et l'objectif du document]

                ### 2. THÈMES PRINCIPAUX
                [Présente les grands thèmes abordés sous forme de liste à puces naturelle]

                ### 3. POINTS CLÉS
                [Présente 3 à 5 informations importantes sous forme de liste à puces naturelle]

                ### 4. PROPOSITIONS
                [Propose 3 questions ou analyses pertinentes suggérées par ce document]
                """
                if not model or model.startswith("gemini"):
                    summary = ask_gemini(summary_prompt, model=model)
                else:
                    summary = ask_ollama(summary_prompt, model=model)
                add_to_history(session_id, "model", summary)

                # Étape 4 : Finalisation de la session
                yield json.dumps({
                    "status": "processing",
                    "step": 4,
                    "message": "Finalisation et initialisation de la session..."
                }) + "\n"
                await asyncio.sleep(0.05)

                yield json.dumps({
                    "status": "completed",
                    "data": {
                        "type": "document_analyzed",
                        "session_id": session_id,
                        "filename": filename,
                        "chunks_indexed": chunks_indexed,
                        "summary": summary
                    }
                }) + "\n"
            except Exception as e:
                yield json.dumps({
                    "status": "error",
                    "message": "Erreur lors de la génération du résumé par l'IA.",
                    "technical": str(e)
                }) + "\n"
                return

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
