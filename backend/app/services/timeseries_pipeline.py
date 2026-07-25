"""timeseries_pipeline.py — Orchestrateur unique pour la génération de modèles
de séries temporelles.

Deux moteurs :
  - "auto" (défaut) : pipeline rigoureux ARIMA/SARIMA (méthodologie A–H) exécuté
    dans le sandbox, avec validation du metrics.json contre le schéma normatif.
    L'agent choisit ARIMA vs SARIMA selon la saisonnalité détectée.
  - "autoforecast" : moteur de prévision automatique (statsforecast) exécuté lui
    aussi dans le sandbox. Il met plusieurs modèles en concurrence et retient le
    premier qui passe les deux gates. Code déterministe, donc pas de génération LLM.

Dans tous les cas, un modèle est enregistré (type "timeseries") et apparaît donc
dans les éléments générés, avec un dashboard dédié.
"""

from app.services.model_specs import MODEL_SPECS, ModelFamily
from app.services.ml_service import generate_timeseries_code, generate_ml_interpretation
from app.services.code_pipeline import run_with_autocorrect
from app.services.session_service import save_timeseries_model_to_db
from app.core import config

_TS_SPEC = MODEL_SPECS[ModelFamily.TIME_SERIES]


def _model_name_from_report(report: dict, fallback: str) -> str:
    modele = (report or {}).get("modele_retenu") or {}
    kind = modele.get("type")
    ordre = modele.get("ordre")
    saison = modele.get("ordre_saisonnier")
    if kind and ordre and saison:
        return f"{kind} {tuple(ordre)}x{tuple(saison)}"
    if kind and ordre:
        return f"{kind} {tuple(ordre)}"
    # Modèle sans ordre (ETS, Theta, SeasonalNaive) : son type suffit à le nommer.
    return kind or fallback


def run_rigorous_timeseries(
    question: str,
    data_context: str,
    file_bytes: bytes,
    filename: str,
    session_id: str,
    history: list | None = None,
    model: str | None = None,
    date_col: str | None = None,
    value_col: str | None = None,
    horizon: int | None = None,
) -> dict:
    """Exécute le pipeline rigoureux ARIMA/SARIMA. Retourne :
    { ok, response, images, model_id, report, error }.
    """
    model = model or config.get_default_model()
    history = history or []
    try:
        code = generate_timeseries_code(
            question, data_context, history, model,
            date_col=date_col, value_col=value_col, horizon=horizon,
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": "Génération du code impossible.",
            "technical": f"{type(exc).__name__}: {exc}",
            "response": "", "images": [], "model_id": None, "report": None,
        }
    if not code:
        return {"ok": False, "error": "Génération du code impossible.", "technical": "Le LLM a renvoyé une réponse vide.", "response": "", "images": [], "model_id": None, "report": None}
    if not file_bytes:
        return {"ok": False, "error": "Génération du code impossible.", "technical": "Aucun fichier de données disponible.", "response": "", "images": [], "model_id": None, "report": None}

    result = run_with_autocorrect(
        initial_code=code,
        file_bytes=file_bytes,
        filename=filename,
        question=question,
        data_context=data_context,
        spec=_TS_SPEC,
        model=model,
    )

    if result.get("error"):
        return {
            "ok": False,
            "error": result["error"].get("simple", "Échec du pipeline."),
            "technical": result["error"].get("technical", ""),
            "response": "",
            "images": result.get("images", []),
            "model_id": None,
            "report": None,
        }

    report = result.get("metrics") or {}
    images = result.get("images", [])
    forecast_chart = images[0] if images else None

    name = _model_name_from_report(report, "Modèle série temporelle")
    model_id = save_timeseries_model_to_db(session_id, name, report, forecast_chart, engine="sarima")

    interpretation = generate_ml_interpretation(
        question,
        _report_summary_for_llm(report),
        data_context,
        bool(images),
        history,
        model,
    )
    statut = report.get("statut_final", "")
    response = (
        f"{interpretation}\n\n"
        f"Un modèle **{name}** a été généré (statut : {statut}). "
        f"Retrouvez son rapport complet (stationnarité, GATE 1/2, prévision) dans "
        f"les modèles générés — cliquez dessus pour ouvrir son dashboard."
    )

    return {"ok": True, "response": response, "images": images, "model_id": model_id, "report": report, "error": None}


def _report_summary_for_llm(report: dict) -> str:
    """Résumé compact du rapport pour nourrir l'interprétation LLM."""
    if not report:
        return "Aucune métrique."
    modele = report.get("modele_retenu", {})
    g1 = report.get("gate_1_diagnostics_residus", {})
    g2 = report.get("gate_2_validation_out_of_sample", {})
    return (
        f"Modèle: {modele.get('type')} ordre={modele.get('ordre')} "
        f"saisonnier={modele.get('ordre_saisonnier')} AIC={modele.get('aic')}. "
        f"GATE1 statut={g1.get('statut')} (Ljung-Box s={g1.get('ljung_box_p_lag_s')}, "
        f"2s={g1.get('ljung_box_p_lag_2s')}). "
        f"GATE2 statut={g2.get('statut')} (MAPE={g2.get('mape_pct')}%, "
        f"couverture IC95={g2.get('couverture_ic95_pct')}%). "
        f"Statut final={report.get('statut_final')}. "
        f"Avertissements={report.get('avertissements')}."
    )


def run_autoforecast_timeseries(
    question: str,
    file_bytes: bytes,
    filename: str,
    session_id: str,
    data_context: str = "",
    history: list | None = None,
    model: str | None = None,
    date_col: str | None = None,
    value_col: str | None = None,
    horizon: int | None = None,
) -> dict:
    """Moteur de prévision automatique : met plusieurs modèles statistiques en
    concurrence dans le sandbox et retient le meilleur sur holdout.

    Contrairement au pipeline rigoureux, le code exécuté est déterministe (pas de
    génération LLM, donc pas d'autocorrection nécessaire). Le LLM n'intervient que
    pour l'interprétation finale.
    """
    from app.services.timeseries_service import run_autoforecast

    model = model or config.get_default_model()
    history = history or []

    if not date_col or not value_col:
        return {
            "ok": False,
            "error": "Colonnes de la série non précisées.",
            "technical": "run_autoforecast_timeseries requiert date_col et value_col.",
            "response": "", "images": [], "model_id": None, "report": None,
        }

    result = run_autoforecast(
        file_bytes=file_bytes, filename=filename,
        date_col=date_col, value_col=value_col, horizon=horizon,
    )

    if result.get("error"):
        # Secours : le pipeline rigoureux, dont le code est généré puis autocorrigé.
        fallback = run_rigorous_timeseries(
            question=question, data_context=data_context, file_bytes=file_bytes,
            filename=filename, session_id=session_id, history=history, model=model,
            date_col=date_col, value_col=value_col, horizon=horizon,
        )
        if fallback.get("ok"):
            fallback["response"] = (
                f"{fallback['response']}\n\n"
                f"Le moteur de prévision automatique a échoué "
                f"({result['error'].get('simple', 'raison inconnue')}) : le pipeline "
                f"ARIMA/SARIMA rigoureux a été utilisé à la place."
            )
            return fallback

        auto_reason = result["error"].get("simple", "Échec du moteur automatique.")
        return {
            "ok": False,
            "error": f"{auto_reason} Le secours ARIMA/SARIMA a également échoué : {fallback.get('error', 'raison inconnue.')}",
            "technical": fallback.get("technical", result["error"].get("technical", "")),
            "response": "", "images": [], "model_id": None, "report": None,
        }

    report = result.get("metrics") or {}
    images = result.get("images", [])
    forecast_chart = images[0] if images else None

    name = _model_name_from_report(report, "Prévision automatique")
    model_id = save_timeseries_model_to_db(
        session_id, name, report, forecast_chart, engine="autoforecast"
    )

    interpretation = generate_ml_interpretation(
        question, _report_summary_for_llm(report), data_context,
        bool(images), history, model,
    )
    statut = report.get("statut_final", "")
    response = (
        f"{interpretation}\n\n"
        f"Modèle retenu par le moteur automatique : **{name}** (statut : {statut}). "
        f"Le rapport complet (comparaison des modèles, GATE 1/2, prévision) est "
        f"disponible dans les modèles générés."
    )

    return {"ok": True, "response": response, "images": images,
            "model_id": model_id, "report": report, "error": None}


def _rapport_timecopilot(sortie: dict, fcst: list, historique: list) -> dict:
    """Traduit le contrat de sortie de TimeCopilot en rapport de dashboard.

    On conserve les champs sous leur nom d'origine (`tsfeatures_analysis`,
    `reason_for_selection`…) : c'est le vocabulaire de l'outil, et le dashboard
    les affiche tels quels plutôt que de les diluer dans un texte libre.
    """
    modele = sortie.get("selected_model") or "TimeCopilot"
    bat_baseline = sortie.get("is_better_than_seasonal_naive")

    avertissements = []
    if bat_baseline is False:
        # Signal important : le modèle retenu ne fait pas mieux qu'une simple
        # répétition de la saison précédente. La prévision reste affichable,
        # mais l'utilisateur doit le savoir.
        avertissements.append(
            "Le modèle retenu ne bat PAS la baseline SeasonalNaive : une simple "
            "répétition du cycle précédent serait aussi performante. Prévision à "
            "considérer avec prudence."
        )

    return {
        "moteur": "timecopilot",
        "modele_retenu": {"type": modele},
        # Contrat TimeCopilot, conservé intégralement pour le dashboard.
        # `tsfeatures_results` et `cross_validation_results` figurent au README
        # mais pas dans la sortie de la 0.0.28 : on les lit quand même, pour
        # rester compatible si une version future les rétablit.
        "tsfeatures_results": sortie.get("tsfeatures_results") or [],
        "tsfeatures_analysis": sortie.get("tsfeatures_analysis") or "",
        "model_details": sortie.get("model_details") or "",
        "cross_validation_results": sortie.get("cross_validation_results") or [],
        # Nom de la métrique comparée (MASE en pratique) : sans lui, les scores
        # du tableau sont des nombres sans unité.
        "cross_validation_metric": sortie.get("cross_validation_metric") or "",
        "model_comparison": sortie.get("model_comparison") or "",
        "is_better_than_seasonal_naive": bat_baseline,
        "reason_for_selection": sortie.get("reason_for_selection") or "",
        "forecast_analysis": sortie.get("forecast_analysis") or "",
        # Présent dans TimeCopilot 0.0.28 mais absent du README (contrat plus
        # ancien) : l'agent signale les points aberrants de la série, ce qui
        # explique souvent une prévision décevante.
        "anomaly_analysis": sortie.get("anomaly_analysis") or "",
        "user_query_response": sortie.get("user_query_response") or "",
        # TimeCopilot valide par cross-validation, pas par les GATE de la
        # méthodologie SARIMA : ne pas prétendre le contraire.
        "gate_1_diagnostics_residus": {"statut": "NON_CALCULE"},
        "gate_2_validation_out_of_sample": {"statut": "NON_CALCULE"},
        "statut_final": "INFO_TIMECOPILOT",
        "avertissements": avertissements,
        "historique": historique,
        "prevision": fcst,
    }


def run_timecopilot_timeseries(
    question: str,
    file_bytes: bytes,
    filename: str,
    session_id: str,
    data_context: str = "",
    history: list | None = None,
    model: str | None = None,
    date_col: str | None = None,
    value_col: str | None = None,
    horizon: int | None = None,
) -> dict:
    """Exécute le vrai TimeCopilot (venv dédié, sous-processus).

    Aucun repli silencieux vers un autre moteur : si TimeCopilot est indisponible
    ou le modèle inadapté, on le dit. L'utilisateur a choisi ce moteur.
    """
    import io

    import pandas as pd

    from app.services.timecopilot_service import (
        TimeCopilotIndisponible, lancer_forecast,
    )

    model = model or config.get_default_model()
    history = history or []

    if not date_col or not value_col:
        return {"ok": False, "error": "Colonnes de la série non précisées.",
                "technical": "run_timecopilot_timeseries requiert date_col et value_col.",
                "response": "", "images": [], "model_id": None, "report": None}

    try:
        ext = (filename or "").rsplit(".", 1)[-1].lower()
        df = (pd.read_csv(io.BytesIO(file_bytes)) if ext == "csv"
              else pd.read_excel(io.BytesIO(file_bytes)))
        csv_text = df.to_csv(index=False)
    except Exception as exc:
        return {"ok": False, "error": "Lecture du fichier impossible.",
                "technical": f"{type(exc).__name__}: {exc}",
                "response": "", "images": [], "model_id": None, "report": None}

    try:
        brut = lancer_forecast(
            csv_text=csv_text, date_col=date_col, value_col=value_col,
            question=question, model=model, horizon=horizon,
        )
    except TimeCopilotIndisponible as exc:
        return {"ok": False, "error": str(exc), "technical": "TimeCopilotIndisponible",
                "response": "", "images": [], "model_id": None, "report": None}

    if not brut.get("ok"):
        err = brut.get("error") or {}
        return {"ok": False, "error": err.get("simple", "Échec de TimeCopilot."),
                "technical": err.get("technical", ""),
                "response": "", "images": [], "model_id": None, "report": None}

    sortie = brut.get("result") or {}
    fcst = brut.get("fcst") or []

    # Série observée, pour que le dashboard superpose historique et prévision.
    historique = []
    try:
        obs = df[[date_col, value_col]].copy()
        obs[date_col] = pd.to_datetime(obs[date_col], errors="coerce")
        obs[value_col] = pd.to_numeric(obs[value_col], errors="coerce")
        obs = obs.dropna().sort_values(date_col)
        historique = [{"date": str(d.date()), "valeur": float(v)}
                      for d, v in zip(obs[date_col], obs[value_col])]
    except Exception:
        pass

    report = _rapport_timecopilot(sortie, fcst, historique)
    nom = f"TimeCopilot — {report['modele_retenu']['type']}"
    model_id = save_timeseries_model_to_db(session_id, nom, report, None, engine="timecopilot")

    # TimeCopilot rédige déjà ses propres analyses : les reprendre telles quelles
    # plutôt que de payer un appel LLM supplémentaire pour paraphraser.
    morceaux = [p for p in (
        sortie.get("user_query_response"),
        sortie.get("forecast_analysis"),
        sortie.get("reason_for_selection"),
        sortie.get("anomaly_analysis"),
    ) if p]
    response = "\n\n".join(morceaux) if morceaux else "Prévision TimeCopilot générée."
    if report.get("avertissements"):
        response += "\n\n⚠️ " + report["avertissements"][0]
    response += (
        f"\n\nModèle retenu : **{report['modele_retenu']['type']}**. "
        f"Le rapport complet (caractéristiques de la série, comparaison des "
        f"modèles, tableau de prévision téléchargeable) est dans les modèles générés."
    )

    return {"ok": True, "response": response, "images": [],
            "model_id": model_id, "report": report, "error": None}
