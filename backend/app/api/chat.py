from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import asyncio
# `dumps_safe` et non `json.dumps` : un `NaN` (statistique non calculable, cellule
# vide) serait écrit tel quel, alors qu'il n'existe pas en JSON. `JSON.parse`
# rejetterait la ligne et le client passerait à la suivante — la réponse serait
# perdue. Un StreamingResponse ne bénéficie pas de `SafeJSONResponse`.
from app.core.json_utils import dumps_safe

def to_thread(func, /, *args, **kwargs):
    """Raccourci vers asyncio.to_thread : tous les appels LLM/pandas/sandbox de
    ce module sont synchrones et bloqueraient sinon la boucle d'événements pour
    toutes les autres sessions pendant toute leur durée (jusqu'à 180s pour un
    tournoi ML ou un grid search SARIMA)."""
    return asyncio.to_thread(func, *args, **kwargs)
from app.services.gemini_service import (
    ask_gemini, generate_stats_code, generate_transformation_code,
    generate_visualization_code, response_language,
)
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

DATASET_INTENTS = ("stat_descriptive", "series_temporelles", "visualisation", "ml",
                   "analyse", "transformation")

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
    # Langue de réponse : "fr" par défaut (le produit est francophone). Les
    # campagnes d'évaluation passent "en" — voir gemini_service.response_language.
    language: Optional[str] = None
    # Jeu de données interrogé, quand la session en porte plusieurs. Absent, on
    # retombe sur le fichier principal — le comportement d'avant le multi-fichier.
    dataset_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str
    images: Optional[List[str]] = []
    # Graphiques structurés, rendus en interactif par le client. Distincts des
    # `images` (PNG matplotlib), qui restent le repli quand le code produit une
    # figure non convertible.
    charts: Optional[List[dict]] = []
    sources: Optional[List[dict]] = []
    # Vrai quand l'échange a modifié les données de la session.
    dataset_changed: bool = False


# Formulations d'annulation. Restreintes volontairement : « annule » suivi d'un
# complément explicite, jamais un simple « non » ou « retour », qui reviendraient
# trop souvent dans une conversation ordinaire.
_MOTIFS_ANNULATION = (
    r"annul\w*\s+(l[ae]\s+)?(derni[eè]re?\s+)?(modif\w*|changement|transformation)",
    r"(reviens|revenir|retourne[rz]?)\s+(à|a)\s+(l['’\s]?[ée]tat|la\s+version)\s+(pr[ée]c[ée]dent|d['’\s]?avant|ant[ée]rieur)",
    r"(restaure|r[ée]tablis)\w*\s+(l['’\s]?[ée]tat|la\s+version)\s+(pr[ée]c[ée]dent|d['’\s]?avant)",
    r"^\s*annuler?\s*$",
    r"d[ée]fai[ts]\w*\s+(la\s+)?(derni[eè]re\s+)?modif",
)


def _est_demande_annulation(message: str) -> bool:
    import re

    texte = (message or "").strip().lower()
    return any(re.search(motif, texte) for motif in _MOTIFS_ANNULATION)


def _dataset_courant(session_id: str) -> str | None:
    """Jeu visé par défaut : celui que le chat interroge sans précision."""
    from app.services.session_service import list_datasets

    jeux = list_datasets(session_id)
    return jeux[0]["id"] if jeux else None


def _nom_csv(filename: str | None) -> str:
    """Le tableau modifié ressort en CSV : l'extension doit suivre, faute de quoi
    toute la chaîne tenterait de le relire avec `read_excel`."""
    base = (filename or "donnees").rsplit(".", 1)[0]
    return f"{base}.csv"


def _resume_tableau(file_bytes: bytes, filename: str | None) -> dict:
    """Dimensions du tableau AVANT modification, pour pouvoir dire ce qui a changé."""
    import io

    import pandas as pd

    try:
        if (filename or "").lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception:
        return {}
    return {"lignes": len(df), "colonnes": len(df.columns), "noms": [str(c) for c in df.columns]}


def _compte_rendu_modification(enregistrement: dict, avant: dict, apres: dict,
                               sortie_code: str) -> str:
    """Ce que l'utilisateur lit après une modification.

    Les chiffres avant/après priment sur la prose : ce sont eux qui permettent
    de repérer une transformation qui a fait plus que demandé.
    """
    lignes = [f"**{enregistrement['filename']}** modifié (version {enregistrement['version']})."]
    if enregistrement.get("format_change"):
        lignes.append("Le fichier est désormais enregistré au format CSV.")

    if avant:
        delta_l = apres["lignes"] - avant["lignes"]
        delta_c = apres["colonnes"] - avant["colonnes"]
        lignes.append("")
        lignes.append(f"- Lignes : {avant['lignes']} → {apres['lignes']}"
                      + (f" ({delta_l:+d})" if delta_l else ""))
        lignes.append(f"- Colonnes : {avant['colonnes']} → {apres['colonnes']}"
                      + (f" ({delta_c:+d})" if delta_c else ""))

        retirees = [c for c in avant["noms"] if c not in apres["noms"]]
        ajoutees = [c for c in apres["noms"] if c not in avant["noms"]]
        if retirees:
            lignes.append(f"- Colonnes disparues : {', '.join(retirees)}")
        if ajoutees:
            lignes.append(f"- Colonnes apparues : {', '.join(ajoutees)}")

    if sortie_code and sortie_code.strip():
        lignes.append("")
        lignes.append(sortie_code.strip())

    lignes.append("")
    lignes.append("_Dites « annule la dernière modification » pour revenir à l'état précédent._")
    return "\n".join(lignes)


def _step(phase: str, message: str) -> dict:
    """Étape de travail annoncée au client pendant qu'il patiente.

    `phase` sert de clé stable au frontend (icône, couleur), `message` est le
    libellé affiché.
    """
    return {"type": "step", "phase": phase, "message": message}


async def _run_dataset_intent(intent, session_id, message, model, history, file_bytes,
                              filename, data_context, dataset_id=None):
    """Exécute l'intention détectée (statistiques / séries temporelles / sandbox de code)
    sur un dataset — qu'il s'agisse du fichier principal d'une session tabulaire
    ou d'un tableau attaché à une session document.

    Générateur : émet des étapes puis un unique événement `result`.
    """
    images = []
    charts = []

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

    # ── Statistiques descriptives : code généré, puis exécuté dans le sandbox ──
    #    Même chemin que les autres intentions calculatoires. Un échec n'est pas
    #    rattrapé par une réponse conversationnelle : sur une question chiffrée,
    #    un modèle qui répond de mémoire présente une estimation comme un calcul.
    if intent == "stat_descriptive":
        if file_bytes:
            yield _step("coding", "Génération du code de calcul…")
            code = await to_thread(generate_stats_code, message, data_context, history, model)

            if not code:
                yield {"type": "result",
                       "response": "Le code de calcul n'a pas pu être généré. Reformulez la "
                                   "question, ou réessayez avec un autre modèle.",
                       "images": [], "charts": []}
                return

            yield _step("compute", "Calcul des statistiques sur vos données…")
            result = await to_thread(
                run_with_autocorrect,
                initial_code=code,
                file_bytes=file_bytes,
                filename=filename,
                question=message,
                data_context=data_context,
                model=model,
            )

            if result["error"]:
                technical = result["error"]["technical"]
                simple = result["error"]["simple"]
                response = f"```\n{technical}\n```\n\nPour faire simple : {simple}"
            else:
                images = result["images"]
                charts = result.get("charts", [])
                raw_output = result["output"]

                # Prompt intégralement dans la langue cible : une consigne de
                # langue isolée au milieu d'un texte français est ignorée, le
                # modèle suivant la langue dominante du prompt.
                from app.services.chart_spec import describe_for_llm
                resume_graphiques = describe_for_llm(charts) or (
                    "Un graphique a été généré." if images else ""
                )
                if response_language.get() == "en":
                    interp_prompt = f"""
{data_context}
The user asked: {message}
Result of the statistical analysis: {raw_output}
{resume_graphiques}

Present this result clearly and accessibly (2-4 sentences), in English.
Do not repeat the raw figures if the result speaks for itself — explain what they mean.
If the user asked for a specific answer format, reproduce it EXACTLY, first, before any commentary.
"""
                else:
                    interp_prompt = f"""
{data_context}
L'utilisateur a demandé : {message}
Résultat de l'analyse statistique : {raw_output}
{resume_graphiques}

Présente ce résultat de façon claire et accessible en français (2-4 phrases).
Ne répète pas les chiffres bruts si le résultat parle de lui-même — explique leur signification.
"""
                yield _step("interpreting", "Interprétation des résultats…")
                interpretation = await to_thread(ask_gemini, prompt=interp_prompt, history=history, model=model)
                response = f"{raw_output}\n\n---\n\n{interpretation}" if raw_output else interpretation
        else:
            yield _step("thinking", "Réflexion…")
            response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
        yield {"type": "result", "response": response, "images": images, "charts": charts}
        return

    # ── Modification du jeu de données ──
    if intent == "transformation":
        if not file_bytes:
            yield {"type": "result", "images": [], "charts": [],
                   "response": "Aucun jeu de données n'est ouvert : importez un fichier "
                               "avant de demander une modification."}
            return

        from app.services.analysis_service import analyze_tabular
        from app.services.session_service import (
            annuler_derniere_modification, remplacer_dataset,
        )

        dataset_vise = dataset_id or _dataset_courant(session_id)

        # « Annule la dernière modification » ne demande aucun code : c'est une
        # opération exacte, il serait absurde de la confier à un modèle.
        if _est_demande_annulation(message):
            retour = await to_thread(annuler_derniere_modification, session_id, dataset_vise)
            if retour["status"] != "ok":
                yield {"type": "result", "response": retour["message"], "images": [], "charts": []}
                return
            yield {"type": "result", "images": [], "charts": [], "dataset_changed": True,
                   "response": (
                       f"Modification annulée : **{retour['filename']}** est revenu à son "
                       f"état précédent (version {retour['version']}).\n\n"
                       f"Modification défaite : _{retour['motif']}_"
                   )}
            return

        yield _step("coding", "Génération du code de modification…")
        code = await to_thread(generate_transformation_code, message, data_context, history, model)
        if not code:
            yield {"type": "result", "images": [], "charts": [],
                   "response": "Le code de modification n'a pas pu être généré. "
                               "Reformulez la demande, ou réessayez avec un autre modèle."}
            return

        yield _step("executing", "Application de la modification…")
        result = await to_thread(
            run_with_autocorrect,
            initial_code=code,
            file_bytes=file_bytes,
            filename=filename,
            question=message,
            data_context=data_context,
            model=model,
        )

        if result["error"]:
            technical = result["error"]["technical"]
            simple = result["error"]["simple"]
            yield {"type": "result", "images": [], "charts": [],
                   "response": f"La modification n'a pas été appliquée.\n\n```\n{technical}\n```"
                               f"\n\nPour faire simple : {simple}"}
            return

        nouveau_csv = result.get("dataset")
        if not nouveau_csv:
            # Le code a tourné sans appeler emit_dataset : rien n'a été enregistré.
            # Le dire, plutôt que de laisser croire que les données ont changé.
            yield {"type": "result", "images": [], "charts": result.get("charts", []),
                   "response": "Aucune modification n'a été enregistrée — le code exécuté "
                               "n'a pas produit de nouveau tableau. "
                               f"{result['output'] or ''}".strip()}
            return

        yield _step("compute", "Enregistrement de la nouvelle version…")
        avant = await to_thread(_resume_tableau, file_bytes, filename)
        analyse = await analyze_tabular(
            nouveau_csv, _nom_csv(filename), model=model, with_interpretation=False,
        )
        if analyse.get("status") == "error":
            yield {"type": "result", "images": [], "charts": [],
                   "response": "Le tableau produit n'a pas pu être relu : la modification "
                               "n'a pas été enregistrée, vos données sont intactes."}
            return

        enregistrement = await to_thread(
            remplacer_dataset, session_id, dataset_vise, nouveau_csv,
            analyse["profile"], analyse["stats"], message, _nom_csv(filename),
        )
        if enregistrement["status"] != "ok":
            yield {"type": "result", "response": enregistrement["message"],
                   "images": [], "charts": []}
            return

        apres = {"lignes": analyse["profile"]["rows"], "colonnes": analyse["profile"]["columns"],
                 "noms": analyse["profile"]["column_names"]}
        yield {"type": "result", "images": [], "charts": result.get("charts", []),
               "dataset_changed": True,
               "response": _compte_rendu_modification(
                   enregistrement, avant, apres, result["output"],
               )}
        return

    # ── Séries temporelles : pipeline rigoureux ARIMA/SARIMA (méthodologie A–H),
    #    repli sur le moteur de prévision automatique. Dans les deux cas un modèle
    #    est sauvegardé (dashboard). ──
    if intent == "series_temporelles":
        if file_bytes:
            from app.services.prompt_budget import profil_modele
            from app.services.timeseries_pipeline import run_rigorous_timeseries, run_autoforecast_timeseries
            from app.services.timeseries_service import infer_series_columns

            # ── Choix du moteur selon ce que le modèle sait faire ──────────────
            # Le pipeline rigoureux fait ÉCRIRE au modèle la méthodologie A–H :
            # ~80 lignes de consignes, deux gates bloquants, un schéma JSON exact.
            # Un petit modèle local n'y arrive pas — il produit du code cassé,
            # épuise les tours d'autocorrection, et l'on se replie de toute façon
            # sur le moteur déterministe, plusieurs minutes et plusieurs appels
            # plus tard. Autant y aller directement.
            #
            # Rien n'est perdu en capacité, seul l'ORDRE change : le moteur
            # automatique garde lui-même le pipeline rigoureux en secours interne.
            # Ici l'utilisateur n'a choisi aucun moteur (contrairement à
            # /models/train-timeseries, où son choix explicite est respecté) : c'est
            # donc bien à l'application de trancher.
            if not profil_modele(model).consignes_denses:
                date_col, value_col = await to_thread(infer_series_columns, file_bytes, filename)
                if date_col and value_col:
                    yield {"type": "step", "phase": "model_generating",
                           "message": "Prévision automatique (modèles statistiques en concurrence)…"}
                    auto = await to_thread(
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
                    if auto["ok"]:
                        yield {"type": "result", "response": auto["response"], "images": auto["images"], "charts": auto.get("charts", []), "model_id": auto.get("model_id"), "model_type": "timeseries"}
                        return

                    # Échec : le moteur automatique a DÉJÀ tenté le pipeline
                    # rigoureux en secours interne. Les deux ont échoué — inutile de
                    # redemander la méthodologie A–H à un modèle qui vient d'échouer.
                    yield _step("thinking", "Réflexion…")
                    response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
                    yield {"type": "result", "response": response, "images": images}
                    return
                # Colonnes indéterminables : le moteur automatique les exige, on
                # retombe sur le chemin nominal ci-dessous.

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
                yield {"type": "result", "response": ts["response"], "images": ts["images"], "charts": ts.get("charts", []), "model_id": ts.get("model_id"), "model_type": "timeseries"}
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
                    yield {"type": "result", "response": tc["response"], "images": tc["images"], "charts": tc.get("charts", []), "model_id": tc.get("model_id"), "model_type": "timeseries"}
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
                       "images": res.get("images", []), "charts": res.get("charts", []),
                       "model_id": res.get("model_id"),
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
                charts = result.get("charts", [])
                models_data = result.get("models", [])

                yield _step("interpreting", "Interprétation des résultats…")
                if intent == "ml":
                    metrics_str = str(result.get("metrics")) if result.get("metrics") else result.get("output", "")
                    response = await to_thread(
                        generate_ml_interpretation,
                        message, metrics_str, data_context,
                        bool(images or charts), history, model
                    )
                else:
                    # Le rédacteur ne voit pas les graphiques : sans ce descriptif
                    # il écrit « voir le graphique » sans savoir ce qu'il montre.
                    from app.services.chart_spec import describe_for_llm
                    resume_graphiques = describe_for_llm(charts) or (
                        "Un graphique a été généré." if images else ""
                    )
                    interp_prompt = f"""
{data_context}
L'utilisateur a demandé : {message}
Sortie texte du code : {result['output'] or 'Aucune.'}
{resume_graphiques}
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

                yield {"type": "result", "response": response, "images": images, "charts": charts, "model_id": saved_model_id, "model_type": "ml" if saved_model_id else None}
                return
        else:
            yield _step("thinking", "Réflexion…")
            response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
        yield {"type": "result", "response": response, "images": images, "charts": charts}
        return

    # Conversation générale
    yield _step("thinking", "Réflexion…")
    response = await to_thread(ask_gemini, prompt=message, history=history, data_context=data_context, model=model)
    yield {"type": "result", "response": response, "images": images, "charts": charts}


async def _run_chat(request: ChatRequest):
    """Déroulé complet d'un échange, sous forme d'étapes puis d'un `result`."""
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable ou expirée.")

    # Posé une seule fois ici : toutes les branches ci-dessous finissent par
    # appeler `ask_gemini`, qui lit ce contexte pour choisir son prompt système.
    response_language.set((request.language or "fr").lower())

    session_type = get_session_type(request.session_id)
    history = get_history(request.session_id)
    add_to_history(request.session_id, "user", request.message)

    images = []
    charts = []
    sources = []
    response = ""
    # Signale au client que les données de la session ont changé : la liste des
    # sources et le tableau de bord doivent être rechargés.
    dataset_changed = False

    # ── Chemin B : documents ───────────────────────────────────
    # Il n'existe plus de session « visuelle » : un scan est transcrit en texte
    # dès l'upload (cascade OCR, voir ocr_service), donc tout document arrive ici
    # sous forme de texte indexé — lisible par n'importe quel modèle, y compris
    # un Ollama local.
    if session_type == "document":
        embedded_bytes, embedded_filename, _, _ = get_embedded_table(request.session_id)

        # Un tableau est attaché à ce document (rapport PDF...) : si la question
        # est de nature quantitative, on la route vers le même pipeline calcul
        # / sandbox qu'une vraie session tabulaire plutôt que la simple lecture
        # narrative du résumé RAG.
        intent = None
        if embedded_bytes:
            yield _step("thinking", "Analyse de votre question…")
            intent = await to_thread(detect_intent, request.message, request.model)

        if embedded_bytes and intent in DATASET_INTENTS:
            table_context = get_embedded_table_context(request.session_id, model=request.model)
            from app.services.session_service import EMBEDDED_DATASET_ID

            async for event in _run_dataset_intent(
                intent, request.session_id, request.message, request.model, history,
                embedded_bytes, embedded_filename, table_context,
                dataset_id=EMBEDDED_DATASET_ID,
            ):
                if event["type"] == "result":
                    response, images = event["response"], event["images"]
                    charts = event.get("charts", [])
                    dataset_changed = event.get("dataset_changed", False)
                else:
                    yield event
        else:
            from app.services.rag_service import retrieve_context_with_sources
            yield _step("searching", "Recherche des passages pertinents…")
            context, sources = await to_thread(retrieve_context_with_sources, request.session_id, request.message)
            table_context = get_embedded_table_context(request.session_id, model=request.model)
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
        # `request.model` conditionne le budget du contexte : un modèle local reçoit
        # un aperçu borné là où une API en reçoit un complet (voir `prompt_budget`).
        data_context = get_data_context(request.session_id, model=request.model,
                                        dataset_id=request.dataset_id)
        # Les calculs (sandbox, modèles) doivent porter sur le MÊME
        # fichier que celui décrit dans le contexte, sans quoi le modèle
        # raisonnerait sur un jeu et l'on exécuterait le code sur un autre.
        from app.services.session_service import get_dataset
        file_bytes, filename, _, _ = get_dataset(request.session_id, request.dataset_id)
        yield _step("thinking", "Analyse de votre question…")
        intent = await to_thread(detect_intent, request.message, request.model)
        async for event in _run_dataset_intent(
            intent, request.session_id, request.message, request.model, history,
            file_bytes, filename, data_context, dataset_id=request.dataset_id,
        ):
            if event["type"] == "result":
                response, images = event["response"], event["images"]
                charts = event.get("charts", [])
                dataset_changed = event.get("dataset_changed", False)
            else:
                yield event

    add_to_history(request.session_id, "model", response)
    save_message_to_report(request.session_id, "assistant", response, images, sources, charts)

    yield {
        "type": "result",
        "response": response,
        "session_id": request.session_id,
        "images": images,
        "charts": charts,
        "sources": sources,
        "dataset_changed": dataset_changed,
    }


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Même traitement que /chat, mais les étapes intermédiaires sont poussées
    au fil de l'eau (NDJSON) pour que l'interface affiche l'activité en cours."""
    async def event_generator():
        try:
            async for event in _run_chat(request):
                yield dumps_safe(event, ensure_ascii=False) + "\n"
                # Laisse la boucle d'événements écrire la ligne avant que
                # l'étape suivante ne monopolise le thread.
                await asyncio.sleep(0)
        except HTTPException as exc:
            yield dumps_safe({"type": "error", "message": exc.detail}, ensure_ascii=False) + "\n"
        except Exception as exc:  # pragma: no cover - filet de sécurité
            yield dumps_safe({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n"

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
        charts=final.get("charts", []),
        sources=final.get("sources", []),
        dataset_changed=final.get("dataset_changed", False),
    )
