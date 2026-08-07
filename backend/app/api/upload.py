from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import StreamingResponse
from pathlib import Path
import asyncio
# Les événements de ce flux sont sérialisés avec `dumps_safe` et non `json.dumps` :
# un `NaN` de pandas (cellule vide de l'aperçu) est écrit littéralement par la
# bibliothèque standard, or `NaN` n'existe pas en JSON. `JSON.parse` rejette alors
# la ligne côté navigateur, et comme le client passe à la suivante, c'est
# l'événement final qui disparaît — l'import semble ne jamais aboutir.
# `SafeJSONResponse` ne protège pas ici : un StreamingResponse ne passe pas par
# la classe de réponse par défaut.
from app.core.json_utils import dumps_safe
from app.services.ingestion_service import (
    decouper_classeur, detect_file_type, load_tabular, extract_table_from_pdf,
)
from app.services.analysis_service import analyze_tabular
from app.services.session_service import create_session, save_data_context, add_to_history
from app.services.session_service import save_file_bytes, rename_session
from app.services.naming_service import titre_depuis_donnees, titre_depuis_document
from app.services.rag_service import index_document, summarize_document, get_document_chunks
from app.services.gemini_service import complete_text
from app.core.config import get_api_key, PROVIDER_MODELS
from app.core import config

router = APIRouter()


# ── Classeurs à plusieurs feuilles ───────────────────────────────────────────
# La première feuille exploitable devient le jeu principal (chemin d'import
# inchangé) ; les suivantes sont rattachées à la même session, exactement comme
# des fichiers ajoutés ensuite. Deux feuilles de même structure déclenchent donc
# aussi la proposition de fusion existante — le cas « une feuille par année ».

async def _attacher_feuilles(session_id: str, classeur: dict | None, model: str | None) -> list[str]:
    """Rattache les feuilles autres que la principale. Renvoie leurs noms."""
    if not classeur:
        return []

    from app.services.session_service import add_dataset

    ajoutees = []
    for feuille in classeur["feuilles"][1:]:
        # Pas d'interprétation par feuille : ce serait un appel LLM par onglet
        # pour un texte que personne ne lit. Le profil et les statistiques, eux,
        # sont nécessaires au contexte du chat et au tableau de bord.
        analyse = await analyze_tabular(
            feuille["bytes"], feuille["filename"], model=model, with_interpretation=False,
        )
        if analyse.get("status") == "error":
            continue
        add_dataset(
            session_id, feuille["bytes"], feuille["filename"],
            analyse["profile"], analyse["stats"],
            name=feuille["nom_affichage"], source="sheet",
        )
        ajoutees.append(feuille["nom_affichage"])
    return ajoutees


def _resume_feuilles(classeur: dict | None, ajoutees: list[str]) -> dict | None:
    if not classeur:
        return None
    return {
        "total": classeur["total"],
        "principale": classeur["feuilles"][0]["nom"],
        # Nom affiché du jeu principal : le client montre la feuille retenue et
        # non le nom du classeur, sinon l'intitulé changerait au rafraîchissement
        # (la liste des jeux, elle, nomme bien la feuille).
        "principale_affichage": classeur["feuilles"][0]["nom_affichage"],
        "importees": [f["nom"] for f in classeur["feuilles"]],
        "ajoutees": ajoutees,
        "ignorees": classeur["ignorees"],
    }


def _phrase_feuilles(classeur: dict, ajoutees: list[str]) -> str:
    """Ce qui est dit à l'utilisateur dans la conversation."""
    principale = classeur["feuilles"][0]["nom"]
    phrase = (
        f"**Classeur de {classeur['total']} feuilles.** L'analyse ci-dessus porte "
        f"sur « {principale} »."
    )
    if ajoutees:
        phrase += (
            f" {len(ajoutees)} autre(s) feuille(s) ont été importées comme jeux de "
            f"données distincts : {', '.join(ajoutees)}. Sélectionnez-en une dans "
            f"le panneau des sources pour l'interroger."
        )
    if classeur["ignorees"]:
        phrase += (
            f" Feuille(s) écartée(s), faute de tableau exploitable : "
            f"{', '.join(classeur['ignorees'])}."
        )
    return phrase


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
    from app.services.ollama_service import list_models

    # `list_models` interroge Ollama en HTTP synchrone (timeout 5 s). Appelé
    # directement, il gèle la boucle d'événements : quand Ollama est absent,
    # tout le backend cesse de répondre pendant 5 s à chaque chargement de page,
    # y compris les requêtes que le frontend lance en parallèle.
    models = await asyncio.to_thread(list_models)

    proprietary = []
    if get_api_key("gemini"):
        proprietary.append("gemini-3.1-flash-lite-preview")
    for provider, provider_models in PROVIDER_MODELS.items():
        if provider == "gemini":
            continue  # Déjà géré ci-dessus avec la convention de nom nu.
        if provider == "custom":
            # Pas de catalogue : le fournisseur « Autre » n'expose que le modèle
            # saisi par l'utilisateur, et seulement s'il est complètement
            # configuré (clé + URL, sinon l'appel échouerait à la première
            # question).
            modele = config.get_custom_model()
            if modele and get_api_key("custom") and config.get_custom_base_url():
                proprietary.append(f"custom/{modele}")
            continue
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
        yield dumps_safe({
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
            yield dumps_safe({
                "status": "error",
                "message": "Une erreur est survenue lors de la lecture du fichier.",
                "technical": str(e)
            }) + "\n"
            return

        if file_type == "unsupported":
            yield dumps_safe({
                "status": "error",
                "message": "Format non supporté. Utilisez CSV, Excel, PDF, DOCX, Markdown ou LaTeX.",
                "technical": "Unsupported file format"
            }) + "\n"
            return

        if file_type == "document":
            embedded_table_df = None
            is_pdf = Path(filename).suffix.lower() == ".pdf"
            yield dumps_safe({
                "status": "processing",
                "step": 1,
                "message": "Lecture du document..."
            }) + "\n"
            await asyncio.sleep(0.05)

            if is_pdf:
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
            # Un classeur à plusieurs feuilles est éclaté en autant de jeux de
            # données : sans ça, seule la première feuille serait lue — et une
            # page de garde en première position ferait analyser la couverture
            # à la place des données.
            classeur = await asyncio.to_thread(decouper_classeur, file_bytes, filename)
            if classeur:
                principale = classeur["feuilles"][0]
                file_bytes, filename = principale["bytes"], principale["filename"]
                yield dumps_safe({
                    "status": "processing",
                    "step": 2,
                    "message": (
                        f"Classeur de {classeur['total']} feuilles : "
                        f"{len(classeur['feuilles'])} importée(s) comme jeux distincts..."
                    ),
                }) + "\n"
                await asyncio.sleep(0.05)

            # Étape 2 : Analyse structurelle
            yield dumps_safe({
                "status": "processing",
                "step": 2,
                "message": "Analyse structurelle et calcul des statistiques..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                check = await asyncio.to_thread(load_tabular, file_bytes, filename)
                if check["status"] == "error":
                    yield dumps_safe({
                        "status": "error",
                        "message": "Votre fichier n'a pas pu être lu. Vérifiez qu'il n'est pas corrompu.",
                        "technical": check.get("message", "Error loading tabular data")
                    }) + "\n"
                    return

            except Exception as e:
                yield dumps_safe({
                    "status": "error",
                    "message": "Erreur d'analyse des données tabulaires.",
                    "technical": str(e)
                }) + "\n"
                return

            # Étape 3 : Interprétation IA
            yield dumps_safe({
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
                    yield dumps_safe({
                        "status": "error",
                        "message": "Une erreur est survenue lors de l'analyse des données.",
                        "technical": result.get("message", "Unknown error in analysis")
                    }) + "\n"
                    return

                # Étape 4 : Initialisation de la session
                yield dumps_safe({
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
                    feuilles_jointes = await _attacher_feuilles(
                        attach_to_session, classeur, model,
                    )
                    yield dumps_safe({
                        "status": "completed",
                        "data": {
                            "type": "dataset_added",
                            "session_id": attach_to_session,
                            "dataset_id": dataset_id,
                            "filename": filename,
                            "profile": result["profile"],
                            "stats": result["stats"],
                            "interpretation": result["interpretation"],
                            "feuilles": _resume_feuilles(classeur, feuilles_jointes),
                        }
                    }) + "\n"
                    return

                session_id = create_session()
                save_data_context(session_id, result["profile"], result["stats"], filename)
                from app.services.session_service import save_initial_analysis
                save_file_bytes(session_id, file_bytes, filename)

                feuilles_jointes = await _attacher_feuilles(session_id, classeur, model)
                if classeur:
                    # Dit dans la conversation, pas seulement dans un statut
                    # fugace : importer trois jeux de données en silence est
                    # exactement ce qu'il ne faut pas faire.
                    result["interpretation"] = (
                        (result["interpretation"] or "").rstrip()
                        + "\n\n" + _phrase_feuilles(classeur, feuilles_jointes)
                    ).strip()

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

                yield dumps_safe({
                    "status": "completed",
                    "data": {
                        "type": "tabular_analyzed",
                        "session_id": session_id,
                        "title": titre,
                        "profile": result["profile"],
                        "stats": result["stats"],
                        "interpretation": result["interpretation"],
                        "feuilles": _resume_feuilles(classeur, feuilles_jointes),
                    }
                }) + "\n"
            except Exception as e:
                yield dumps_safe({
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
            yield dumps_safe({
                "status": "processing",
                "step": 2,
                "message": "Découpage et indexation vectorielle du document..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                # Rattachement à une session ouverte : le document rejoint la
                # collection ChromaDB existante (`index_document` fait
                # `get_or_create_collection` puis `add`, avec le nom du fichier
                # en métadonnée). Ni le titre ni l'historique ne sont touchés —
                # on ajoute une source, on ne recommence pas une session.
                document_ajoute = bool(attach_to_session)
                session_id = attach_to_session or create_session()
                if not document_ajoute:
                    set_session_type(session_id, "document")

                if index_doc.lower() == "true":
                    index_result = await asyncio.to_thread(index_document, session_id, file_bytes, filename)
                    chunks_indexed = index_result.get("chunks_indexed", 0)
                else:
                    chunks_indexed = 0
            except Exception as e:
                yield dumps_safe({
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
                        if document_ajoute:
                            # `save_embedded_table` écrit dans l'unique emplacement
                            # de la session : sur un document ajouté, il écraserait
                            # le tableau du document précédent.
                            from app.services.session_service import add_dataset
                            add_dataset(session_id, table_csv_bytes, table_filename,
                                        table_check["profile"], table_stats,
                                        name=f"Tableau extrait — {table_filename}",
                                        source="extracted_table")
                        else:
                            save_embedded_table(session_id, table_csv_bytes, table_filename,
                                                table_check["profile"], table_stats)
                        has_embedded_table = True
                except Exception:
                    pass  # Le résumé du document reste utile même si le dataset secondaire échoue.

            if document_ajoute:
                # Source ajoutée à une session ouverte : elle est indexée et
                # interrogeable. Pas de résumé ni de renommage — la session garde
                # son sujet, on lui a seulement donné une source de plus.
                yield dumps_safe({
                    "status": "completed",
                    "data": {
                        "type": "document_added",
                        "session_id": session_id,
                        "filename": filename,
                        "chunks_indexed": chunks_indexed,
                        "has_embedded_table": has_embedded_table,
                    }
                }) + "\n"
                return

            # Étape 3 : Analyse et résumé IA
            yield dumps_safe({
                "status": "processing",
                "step": 3,
                "message": "Analyse et génération du résumé par l'IA..."
            }) + "\n"
            await asyncio.sleep(0.05)

            try:
                from app.services.rag_service import extract_text_from_document
                raw_context = await asyncio.to_thread(extract_text_from_document, file_bytes, filename)
                if index_doc.lower() == "true" and chunks_indexed > 0:
                    indexed_context = await asyncio.to_thread(summarize_document, session_id, model=model)
                    if indexed_context.strip():
                        raw_context = indexed_context
                else:
                    raw_context = " ".join(raw_context.split()[:2400])  # Prend environ le même nombre de mots que 6 chunks

                if not raw_context.strip():
                    if Path(filename).suffix.lower() != ".pdf":
                        yield dumps_safe({
                            "status": "error",
                            "message": "Ce document ne contient aucun texte lisible.",
                            "technical": f"Empty document: {filename}",
                        }) + "\n"
                        return
                    # Aucun texte extractible (scan/photo). On lance la cascade OCR :
                    # serveur Unlimited-OCR, puis transcription par le modèle vision
                    # de l'utilisateur, puis RapidOCR en local. Si l'un aboutit, le
                    # document redevient un document texte ordinaire, exploitable par
                    # n'importe quel modèle (y compris un LLM local), avec citations
                    # RAG et extraction de tableau.
                    yield dumps_safe({
                        "status": "processing",
                        "step": 3,
                        "message": "Document scanné détecté — reconnaissance de texte (OCR) en cours..."
                    }) + "\n"
                    await asyncio.sleep(0.05)

                    try:
                        from app.services.ocr_service import ocr_pdf_pages, extract_table_from_ocr
                        # `model` sert au 2e recours (transcription par le modèle
                        # multimodal choisi) ; les deux autres moteurs l'ignorent.
                        ocr_pages = await asyncio.to_thread(ocr_pdf_pages, file_bytes, model=model)
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

                # Les trois moteurs OCR ont échoué : ni serveur Unlimited-OCR, ni
                # modèle multimodal, et RapidOCR n'a rien reconnu (manuscrit, photo
                # floue...). On crée la session malgré tout — perdre l'import serait
                # plus pénible que d'ouvrir une session qui dit franchement ce qui
                # manque — mais sans contexte, le chat ne pourra rien en tirer.
                document_illisible = not raw_context.strip()

                if document_illisible:
                    from app.services.vision_service import supporte_vision

                    raison_vision = (
                        "le modèle sélectionné n'est pas multimodal"
                        if not supporte_vision(model)
                        else "l'appel au modèle a échoué"
                    )
                    summary = (
                        "### Document non lu\n\n"
                        "Ce document est un scan dont **aucun moteur de reconnaissance "
                        "de texte n'a rien pu extraire**. La session est créée, mais "
                        "elle reste vide : les questions posées ici n'auront aucun "
                        "contenu sur lequel s'appuyer.\n\n"
                        "Les trois recours tentés :\n\n"
                        f"1. **Unlimited-OCR** — serveur d'OCR injoignable "
                        f"(voir `README ocr.md` pour le démarrer) ;\n"
                        f"2. **Transcription par le modèle vision** — {raison_vision} "
                        f"(modèle : `{model or 'par défaut'}`) ;\n"
                        "3. **RapidOCR** — n'a rien reconnu, ce qui arrive sur un "
                        "manuscrit ou un scan de mauvaise qualité.\n\n"
                        "**Que faire :** choisir un modèle multimodal (Gemini, GPT-4o, "
                        "Claude, ou un modèle vision local comme llava) puis réimporter ; "
                        "ou fournir une version texte du document ; ou fournir un scan "
                        "de meilleure qualité."
                    )
                    add_to_history(session_id, "model", summary)

                    # Pas de contexte à résumer : le nom du fichier est la seule
                    # description disponible pour titrer la session.
                    titre = Path(filename).stem or filename
                    rename_session(session_id, titre)

                    yield dumps_safe({
                        "status": "processing",
                        "step": 4,
                        "message": "Finalisation et initialisation de la session..."
                    }) + "\n"
                    await asyncio.sleep(0.05)

                    yield dumps_safe({
                        "status": "completed",
                        "data": {
                            "type": "document_analyzed",
                            "session_id": session_id,
                            "title": titre,
                            "filename": filename,
                            "chunks_indexed": 0,
                            "has_embedded_table": False,
                            "summary": summary,
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
                yield dumps_safe({
                    "status": "processing",
                    "step": 4,
                    "message": "Finalisation et initialisation de la session..."
                }) + "\n"
                await asyncio.sleep(0.05)

                yield dumps_safe({
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
                yield dumps_safe({
                    "status": "error",
                    "message": "Erreur lors de la génération du résumé par l'IA.",
                    "technical": str(e)
                }) + "\n"
                return

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")
