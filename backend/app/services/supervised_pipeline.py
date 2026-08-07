"""supervised_pipeline.py — Orchestrateur du tournoi supervisé.

Sans choix explicite, la famille est déduite de la cible (continue → régression ;
catégorielle → classification ; minorité < 20 % → classification déséquilibrée),
les modèles de la famille sont mis en concurrence et le meilleur est livré. Si
l'utilisateur impose un modèle ou des paramètres, le tournoi est désactivé : un
seul estimateur est exécuté avec la configuration validée.

Le seul apport du LLM ici est d'identifier la colonne cible dans la question —
tâche étroite et vérifiable (le nom doit exister dans le jeu de données). Tout le
reste est déterministe : ni code généré, ni autocorrection au hasard.
"""

import io
import logging

from app.core import config
from app.services.supervised_specs import (
    BUDGET_SECONDES, STATUT_AUCUN_UTILE, STATUT_HYPOTHESES_VIOLEES, STATUT_VALIDE,
)

logger = logging.getLogger("app.supervised")


def _charger_df(file_bytes: bytes, filename: str):
    import pandas as pd

    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return (pd.read_csv(io.BytesIO(file_bytes)) if ext == "csv"
            else pd.read_excel(io.BytesIO(file_bytes)))


def detecter_cible(question: str, colonnes: list[str], model: str | None = None) -> str | None:
    """Identifie la colonne à prédire dans la question de l'utilisateur.

    On contraint la réponse à un nom de colonne existant : un LLM qui invente un
    nom est écarté plutôt que de faire échouer le tournoi plus loin.
    """
    if not colonnes:
        return None
    from app.services.gemini_service import complete_text

    prompt = (
        f"Voici les colonnes d'un jeu de données :\n{', '.join(map(str, colonnes))}\n\n"
        f"L'utilisateur demande : « {question} »\n\n"
        f"Quelle colonne cherche-t-il à PRÉDIRE (la variable cible) ?\n"
        f"Réponds UNIQUEMENT par le nom exact d'une colonne de la liste, sans "
        f"aucun autre texte. Si aucune ne convient, réponds AUCUNE."
    )
    try:
        reponse = complete_text(prompt, model or config.get_default_model()).strip()
    except Exception:
        return None

    reponse = reponse.strip().strip('"\'`').strip()
    if reponse in colonnes:
        return reponse
    # Tolère une casse ou des espaces différents, refuse le reste.
    for c in colonnes:
        if str(c).strip().lower() == reponse.lower():
            return c
    return None


def _nom_modele(rapport: dict) -> str:
    retenu = (rapport or {}).get("modele_retenu") or {}
    libelle = retenu.get("libelle") or "Modèle supervisé"
    cible = (rapport or {}).get("cible")
    return f"{libelle} — {cible}" if cible else libelle


def _resume_pour_llm(rapport: dict) -> str:
    """Résumé compact du tournoi, pour nourrir l'interprétation en langage naturel."""
    retenu = (rapport or {}).get("modele_retenu") or {}
    perf = retenu.get("performances") or {}
    lignes = [
        f"Famille : {rapport.get('famille')}. Cible : {rapport.get('cible')}.",
        f"Modèle retenu : {retenu.get('libelle')}.",
        f"Statut : {rapport.get('statut_final')}.",
        f"Performances : {perf}.",
    ]
    candidats = rapport.get("candidats") or []
    if len(candidats) > 1:
        comp = ", ".join(
            f"{c.get('libelle')}={(c.get('performances') or {}).get(rapport.get('metrique_selection'))}"
            for c in candidats
        )
        lignes.append(f"Concurrents : {comp}.")
    if rapport.get("violations"):
        lignes.append(f"Hypothèses/performances en défaut : {rapport['violations']}.")
    if rapport.get("avertissements"):
        lignes.append(f"Avertissements : {rapport['avertissements']}.")
    return "\n".join(lignes)


def run_supervised_tournament(
    question: str,
    file_bytes: bytes,
    filename: str,
    session_id: str,
    data_context: str = "",
    history: list | None = None,
    model: str | None = None,
    target: str | None = None,
    features: list[str] | None = None,
    budget: int | None = None,
    requested_model: str | None = None,
    hyperparameters: dict | None = None,
) -> dict:
    """Met les modèles de la famille en concurrence et persiste le meilleur.

    Returns:
        { ok, response, images, model_id, report, error }
    """
    from app.services.ml_service import generate_ml_interpretation
    from app.services.sandbox_service import execute_code
    from app.services.session_service import save_supervised_model_to_db
    from app.services.supervised_code import build_supervised_code

    model = model or config.get_default_model()
    history = history or []

    def echec(msg: str, tech: str = "") -> dict:
        return {"ok": False, "error": msg, "technical": tech,
                "response": "", "images": [], "model_id": None, "report": None}

    if not file_bytes:
        return echec("Aucun jeu de données disponible.")

    try:
        from app.services.model_request_service import (
            ModelRequest, parse_model_request, validate_model_request,
        )
        parsed = parse_model_request(question)
        request_config = ModelRequest(
            model=requested_model or parsed.model,
            hyperparameters={**parsed.hyperparameters, **(hyperparameters or {})},
            unsupported_parameters=parsed.unsupported_parameters,
        )
        validate_model_request(request_config)
    except ValueError as exc:
        return echec(str(exc), "Configuration d'entraînement invalide.")

    try:
        df = _charger_df(file_bytes, filename)
    except Exception as exc:
        return echec("Lecture du fichier impossible.", f"{type(exc).__name__}: {exc}")

    colonnes = [str(c) for c in df.columns]
    cible = target or detecter_cible(question, colonnes, model)
    if not cible:
        return echec(
            "Impossible d'identifier la variable à prédire. Précisez-la dans votre "
            "question (par exemple « prédire Purchased à partir de Age et Salary »).",
            "Cible non détectée.",
        )

    explicatives = features or [c for c in colonnes if c != cible]
    # Un identifiant n'explique rien et fausse les modèles à base d'arbres.
    explicatives = [
        c for c in explicatives
        if not any(mot in str(c).lower() for mot in ("id", "identifiant", "code", "uuid"))
        or df[c].nunique() < len(df) * 0.5
    ]
    if not explicatives:
        return echec("Aucune variable explicative exploitable.", "Liste de features vide.")

    pipeline_params = dict(request_config.hyperparameters)
    test_size = pipeline_params.pop("test_size", 0.25)
    random_state = pipeline_params.pop("random_state", 42)
    logger.info(
        "Entraînement supervisé : cible=%s, variables=%d, modèle=%s, paramètres=%s",
        cible, len(explicatives), request_config.model or "tournoi", pipeline_params,
    )
    code = build_supervised_code(
        cible,
        explicatives,
        budget=budget or BUDGET_SECONDES,
        requested_model=request_config.model,
        hyperparameters=pipeline_params,
        test_size=test_size,
        random_state=random_state,
    )
    result = execute_code(code, dataframe_bytes=file_bytes, filename=filename)

    if result.get("error"):
        err = result["error"]
        return echec(err.get("simple", "Le tournoi a échoué."), err.get("technical", ""))

    rapport = result.get("metrics")
    if not rapport:
        return echec(
            "Le tournoi n'a produit aucun résultat exploitable.",
            (result.get("output") or "")[:1000],
        )

    rapport["_engine"] = "tournoi_supervise"
    nom = _nom_modele(rapport)

    # Générée avant la persistance pour être stockée dans le rapport : sans ça
    # elle ne vivait que dans la réponse du chat et disparaissait dès que
    # l'utilisateur rouvrait le modèle depuis son dashboard.
    interpretation = generate_ml_interpretation(
        question, _resume_pour_llm(rapport), data_context,
        bool(result.get("images")), history, model,
    )
    rapport["interpretation"] = interpretation

    # Le runner du sandbox remonte les .pkl produits : c'est le pipeline
    # déployable, celui qui sert à la simulation et à l'export.
    artefacts = result.get("models") or []
    model_b64 = artefacts[0].get("model_b64") if artefacts else None
    model_id = save_supervised_model_to_db(session_id, nom, rapport, model_b64=model_b64)

    statut = rapport.get("statut_final")
    qualite = rapport.get("qualite")
    metrique = rapport.get("metrique_qualite") or "performance"
    if statut == STATUT_VALIDE:
        # Franchir le plancher ne vaut pas quitus : on annonce le niveau atteint
        # pour que l'utilisateur juge s'il suffit à SON usage.
        nuance = {
            "faible": (" Attention : sa qualité prédictive reste **faible** — il capte "
                       "un signal réel mais une grande part de la variation lui échappe."),
            "moderee": " Sa qualité prédictive est **modérée**.",
            "bonne": " Sa qualité prédictive est **bonne**.",
            "excellente": " Sa qualité prédictive est **excellente**.",
        }.get(qualite, "")
        verdict = (
            f"Le modèle **{(rapport.get('modele_retenu') or {}).get('libelle')}** a été retenu "
            f"et satisfait toutes les normes (hypothèses statistiques et performances)."
            f"{nuance}"
        )
    elif statut == STATUT_AUCUN_UTILE:
        verdict = (
            "**Aucun modèle utile n'a été trouvé** : aucun des candidats n'apporte "
            "d'information exploitable par rapport à une prédiction triviale. "
            "Les variables disponibles n'expliquent probablement pas cette cible."
        )
    else:
        verdict = (
            f"Le modèle **{(rapport.get('modele_retenu') or {}).get('libelle')}** est le meilleur "
            f"des candidats, mais **{len(rapport.get('violations') or [])} norme(s) ne sont pas "
            f"respectée(s)** — à interpréter avec prudence."
        )

    n_test = len(rapport.get("candidats") or [])
    n_total = len(rapport.get("candidats") or []) if not rapport.get("sortie_anticipee") else None
    detail = (
        f"{n_test} modèle(s) évalué(s) en {rapport.get('duree_secondes', 0):.1f} s"
        + (" — arrêt anticipé, les normes étaient déjà satisfaites." if rapport.get("sortie_anticipee") else ".")
    )

    response = (
        f"{interpretation}\n\n{verdict}\n\n{detail} "
        f"Le rapport complet (hypothèses testées, comparaison des modèles) est "
        f"disponible dans les modèles générés."
    )
    if request_config.model:
        response = (
            f"**Configuration imposée respectée** : `{request_config.model}`"
            f"{f' avec {request_config.hyperparameters}' if request_config.hyperparameters else ''}.\n\n"
            + response
        )

    return {"ok": True, "response": response, "images": result.get("images", []),
            "charts": result.get("charts", []),
            "model_id": model_id, "report": rapport, "error": None}
