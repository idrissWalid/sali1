from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
from pathlib import Path
import json
import asyncio
from app.services.ingestion_service import detect_file_type, load_tabular, extract_table_from_pdf
from app.services.analysis_service import analyze_tabular
from app.services.session_service import create_session, save_data_context, add_to_history
from app.services.session_service import save_file_bytes, rename_session
from app.services.naming_service import titre_depuis_donnees, titre_depuis_document
from app.services.rag_service import index_document, summarize_document, get_document_chunks
from app.services.gemini_service import complete_text
from app.core.config import get_api_key, PROVIDER_MODELS
from app.core import config

router = APIRouter()


def batch_summarize_chunks(chunks: list[str], model: str) -> str:
    if not chunks:
        return ""

    max_batch_size = 6
    max_batches = 8
    batch_summaries = []
    batch_count = min((len(chunks) + max_batch_size - 1) // max_batch_size, max_batches)

    for batch_index in range(batch_count):
        start = batch_index * max_batch_size
        batch = chunks[start:start + max_batch_size]
        prompt = f"""
Voici un extrait d'un document. Rédige un résumé clair et synthétique en français du passage entier.
Ne commence pas par une introduction (pas de 'Bonjour', 'Voici', 'En tant que ...').

{chr(10).join(batch)}

Résumé :
"""
        summary = complete_text(prompt, model)
        batch_summaries.append(summary.strip())

    if len(batch_summaries) == 0:
        return ""
    if len(batch_summaries) == 1:
        return batch_summaries[0]

    combined_prompt = f"""
Tu disposes des résumés intermédiaires de plusieurs parties d'un document.
Regroupe-les et rédige un résumé final unique en français.
Ne commence pas par des formules d'introduction ; va directement à l'essentiel.

{chr(10).join(batch_summaries)}

Résumé final :
"""
    return complete_text(combined_prompt, model)

@router.get("/llm-models")
async def list_llm_models():
    try:
        import subprocess
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')[1:]
        models = [line.split()[0] for line in lines if line]
    except Exception:
        models = []

    proprietary = []
    if get_api_key("gemini"):
        proprietary.append("gemini-3.1-flash-lite-preview")
    for provider, provider_models in PROVIDER_MODELS.items():
        if provider == "gemini":
            continue  # Déjà géré ci-dessus avec la convention de nom nu.
        if get_api_key(provider):
            proprietary.extend(f"{provider}/{m}" for m in provider_models)

    # Modèle par défaut configurable (voir /api/settings/default-model), utilisé
    # par le frontend pour initialiser la sélection tant que l'utilisateur n'a
    # rien choisi lui-même.
    default_model = config.get_default_model()
    all_models = models + proprietary
    if default_model in all_models:
        if default_model in models:
            models.remove(default_model)
            models.insert(0, default_model)
        else:
            proprietary.remove(default_model)
            proprietary.insert(0, default_model)

    return {
        "models": models,
        "proprietary": proprietary,
        "default": default_model,
    }

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    model: str | None = Form(None),
    index_doc: str = Form("true"),
    session_id: str = Form(""),
    skip_interpretation: str = Form("false"),
):
    """Analyse un fichier. Avec `session_id`, le fichier est rattaché comme jeu
    de données supplémentaire à une session existante au lieu d'en créer une.

    `skip_interpretation=true` prépare la session (profil, statistiques, fichier
    stocké) sans produire le texte d'accueil ni le titre déduit — les deux seuls
    appels LLM de l'upload. Réservé aux campagnes d'évaluation, qui posent
    ensuite leurs propres questions via `/api/chat` : le contexte de données
    exploité par le chat est identique, seul le message d'accueil disparaît.
    """
    attach_to_session = session_id.strip() or None
    want_interpretation = skip_interpretation.strip().lower() not in ("true", "1", "yes")

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

        if file_type == "document":
            yield json.dumps({
                "status": "processing",
                "step": 1,
                "message": "Recherche d'un tableau de données dans le PDF..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                embedded_table_df = await asyncio.to_thread(extract_table_from_pdf, file_bytes)
            except Exception:
                embedded_table_df = None

            extracted_df = embedded_table_df
            if extracted_df is not None:
                # Un rapport (texte narratif + tableau) doit rester sur le pipeline
                # document : basculer en mode tabulaire écraserait tout le contexte
                # (titre, intro, conclusion) au profit du seul tableau. On ne
                # reclasse donc que les PDF où le tableau domine largement le
                # contenu (peu ou pas de texte en dehors de lui). Dans le cas
                # rapport, embedded_table_df est conservé pour être attaché à la
                # session document comme dataset secondaire (cf. plus bas).
                from app.services.rag_service import extract_text_from_pdf as _extract_pdf_text
                full_text = await asyncio.to_thread(_extract_pdf_text, file_bytes)
                table_text_len = sum(len(str(v)) for row in extracted_df.itertuples(index=False) for v in row)
                narrative_len = max(len(full_text) - table_text_len, 0)
                if narrative_len > 400:
                    extracted_df = None

            if extracted_df is not None:
                file_bytes = extracted_df.to_csv(index=False).encode("utf-8")
                filename = Path(filename).stem + ".csv"
                file_type = "tabular"
                embedded_table_df = None  # devient le dataset principal, plus un secondaire

        if file_type == "tabular":
            # Étape 2 : Analyse structurelle
            yield json.dumps({
                "status": "processing",
                "step": 2,
                "message": "Analyse structurelle et calcul des statistiques..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                check = await asyncio.to_thread(load_tabular, file_bytes, filename)
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
                result = await analyze_tabular(
                    file_bytes, filename, model=model,
                    with_interpretation=want_interpretation,
                )
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

                if attach_to_session:
                    # Jeu de données ajouté à une session déjà ouverte : on ne
                    # touche ni à son fichier principal ni à son historique.
                    from app.services.session_service import add_dataset
                    dataset_id = add_dataset(
                        attach_to_session, file_bytes, filename,
                        result["profile"], result["stats"], name=filename,
                    )
                    yield json.dumps({
                        "status": "completed",
                        "data": {
                            "type": "dataset_added",
                            "session_id": attach_to_session,
                            "dataset_id": dataset_id,
                            "filename": filename,
                            "profile": result["profile"],
                            "stats": result["stats"],
                            "interpretation": result["interpretation"],
                        }
                    }) + "\n"
                    return

                session_id = create_session()
                save_data_context(session_id, result["profile"], result["stats"], filename)
                from app.services.session_service import save_initial_analysis
                save_file_bytes(session_id, file_bytes, filename)

                if want_interpretation:
                    save_initial_analysis(session_id, result["interpretation"])
                    add_to_history(session_id, "model", result["interpretation"])

                    # Titre déduit du contenu : sans ça, trois imports du même fichier
                    # donnent trois entrées identiques dans l'historique des sessions.
                    titre = await asyncio.to_thread(
                        titre_depuis_donnees,
                        filename, result["profile"], result["interpretation"], model=model,
                    )
                else:
                    # Sans interprétation, il n'y a rien à résumer en un titre et
                    # l'historique reste vide : le nom du fichier suffit.
                    titre = filename
                rename_session(session_id, titre)

                # L'ancien dashboard HTML n'est plus généré ici.
                # Il sera généré à la volée en JSON par /api/dashboard/data/{session_id}

                yield json.dumps({
                    "status": "completed",
                    "data": {
                        "type": "tabular_analyzed",
                        "session_id": session_id,
                        "title": titre,
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
                    index_result = await asyncio.to_thread(index_document, session_id, file_bytes, filename)
                    chunks_indexed = index_result.get("chunks_indexed", 0)
                else:
                    chunks_indexed = 0
            except Exception as e:
                yield json.dumps({
                    "status": "error",
                    "message": "Erreur lors de l'indexation du document.",
                    "technical": str(e)
                }) + "\n"
                return

            has_embedded_table = False
            if embedded_table_df is not None:
                try:
                    from app.services.profiling_service import generate_profiling_stats
                    from app.services.session_service import save_embedded_table

                    table_csv_bytes = embedded_table_df.to_csv(index=False).encode("utf-8")
                    table_filename = Path(filename).stem + ".csv"
                    table_check = await asyncio.to_thread(load_tabular, table_csv_bytes, table_filename)
                    if table_check["status"] == "ok":
                        table_stats = await asyncio.to_thread(generate_profiling_stats, embedded_table_df)
                        save_embedded_table(session_id, table_csv_bytes, table_filename, table_check["profile"], table_stats)
                        has_embedded_table = True
                except Exception:
                    pass  # Le résumé du document reste utile même si le dataset secondaire échoue.

            # Étape 3 : Analyse et résumé IA
            yield json.dumps({
                "status": "processing",
                "step": 3,
                "message": "Analyse et génération du résumé par l'IA..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                from app.services.rag_service import extract_text_from_pdf
                raw_context = await asyncio.to_thread(extract_text_from_pdf, file_bytes)
                if index_doc.lower() == "true" and chunks_indexed > 0:
                    indexed_context = await asyncio.to_thread(summarize_document, session_id, model=model)
                    if indexed_context.strip():
                        raw_context = indexed_context
                else:
                    raw_context = " ".join(raw_context.split()[:2400])  # Prend environ le même nombre de mots que 6 chunks

                if not raw_context.strip():
                    # Aucun texte extractible (scan/photo). On tente d'abord un OCR
                    # local : s'il aboutit, le document redevient un document texte
                    # ordinaire, exploitable par n'importe quel modèle (y compris un
                    # LLM local), avec citations RAG et extraction de tableau.
                    yield json.dumps({
                        "status": "processing",
                        "step": 3,
                        "message": "Document scanné détecté — reconnaissance de texte (OCR) en cours..."
                    }) + "\n"
                    await asyncio.sleep(0.05)

                    try:
                        from app.services.ocr_service import ocr_pdf_pages, extract_table_from_ocr
                        ocr_pages = await asyncio.to_thread(ocr_pdf_pages, file_bytes)
                        ocr_text = "\n\n".join(p["text"] for p in ocr_pages if p["text"].strip()).strip()
                    except Exception:
                        ocr_pages, ocr_text = [], ""

                    if ocr_text:
                        if index_doc.lower() == "true":
                            try:
                                ocr_index = await asyncio.to_thread(
                                    index_document, session_id, file_bytes, filename, text=ocr_text
                                )
                                chunks_indexed = ocr_index.get("chunks_indexed", 0)
                            except Exception:
                                chunks_indexed = 0

                        # Un tableau scanné peut lui aussi devenir un dataset de session.
                        try:
                            from app.services.profiling_service import generate_profiling_stats
                            from app.services.session_service import save_embedded_table

                            ocr_table_df = await asyncio.to_thread(extract_table_from_ocr, ocr_pages)
                            if ocr_table_df is not None:
                                table_csv_bytes = ocr_table_df.to_csv(index=False).encode("utf-8")
                                table_filename = Path(filename).stem + ".csv"
                                table_check = await asyncio.to_thread(load_tabular, table_csv_bytes, table_filename)
                                if table_check["status"] == "ok":
                                    save_embedded_table(
                                        session_id,
                                        table_csv_bytes,
                                        table_filename,
                                        table_check["profile"],
                                        await asyncio.to_thread(generate_profiling_stats, ocr_table_df),
                                    )
                                    has_embedded_table = True
                        except Exception:
                            pass  # Le texte OCR reste utile même sans tableau exploitable.

                        raw_context = " ".join(ocr_text.split()[:2400])

                if not raw_context.strip():
                    # OCR infructueux (photo illisible, écriture manuscrite...) :
                    # dernier recours, retrieval visuel via ColSmolVLM + un modèle
                    # multimodal. Seule branche qui exige la vision — les documents
                    # texte et ceux récupérés par OCR restent lisibles par n'importe
                    # quel modèle, y compris local.
                    from app.services.colsmolvlm_service import index_visual_document, render_pdf_to_images
                    from app.services.vision_service import (
                        VisionNonSupportee, ask_vision, message_refus, supporte_vision,
                    )
                    from app.services.session_service import set_session_type as _set_session_type
                    import io as _io

                    if not supporte_vision(model):
                        # Vérifié AVANT l'indexation ColSmolVLM : celle-ci est
                        # coûteuse et n'aurait aucune utilité sans modèle capable
                        # de lire les pages ensuite.
                        yield json.dumps({
                            "status": "error",
                            "message": message_refus(model or "modèle par défaut"),
                            "technical": f"Modèle sans capacité vision : {model}",
                        }) + "\n"
                        return

                    visual_result = await asyncio.to_thread(index_visual_document, session_id, file_bytes)
                    if visual_result.get("status") != "ok":
                        yield json.dumps({
                            "status": "error",
                            "message": "Le document ne contient pas de texte lisible et l'indexation visuelle (ColSmolVLM) a échoué.",
                            "technical": visual_result.get("message", "Erreur ColSmolVLM inconnue.")
                        }) + "\n"
                        return

                    _set_session_type(session_id, "document_visual")

                    preview_images = (await asyncio.to_thread(render_pdf_to_images, file_bytes))[:4]
                    preview_png_bytes = []
                    for img in preview_images:
                        buf = _io.BytesIO()
                        img.save(buf, "PNG")
                        preview_png_bytes.append(buf.getvalue())

                    summary_prompt = """
                    Voici les premières pages d'un document scanné (image).

                    Rédige un résumé structuré, naturel et fluide en français à partir de ce que tu vois sur ces images.
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
                    try:
                        summary = await asyncio.to_thread(ask_vision, summary_prompt, preview_png_bytes, model=model)
                    except VisionNonSupportee as exc:
                        yield json.dumps({
                            "status": "error",
                            "message": str(exc),
                            "technical": f"Modèle sans capacité vision : {model}",
                        }) + "\n"
                        return
                    add_to_history(session_id, "model", summary)

                    # Document illisible en texte : le résumé issu de la vision est
                    # la seule description exploitable pour titrer la session.
                    titre = await asyncio.to_thread(titre_depuis_document, filename, summary, model=model)
                    rename_session(session_id, titre)

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
                            "title": titre,
                            "filename": filename,
                            "chunks_indexed": 0,
                            "summary": summary
                        }
                    }) + "\n"
                    return

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
                summary = await asyncio.to_thread(ask_gemini, summary_prompt, model=model)
                add_to_history(session_id, "model", summary)

                # Le résumé qu'on vient de produire décrit le document mieux que
                # son nom de fichier : on s'en sert pour titrer la session.
                titre = await asyncio.to_thread(titre_depuis_document, filename, summary or raw_context, model=model)
                rename_session(session_id, titre)

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
                        "title": titre,
                        "filename": filename,
                        "chunks_indexed": chunks_indexed,
                        "has_embedded_table": has_embedded_table,
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
