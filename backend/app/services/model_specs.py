from enum import Enum
from typing import Optional
from pydantic import BaseModel

class ModelFamily(str, Enum):
    LOGISTIC_REGRESSION = "logistic_regression"
    LINEAR_REGRESSION = "linear_regression"
    TREE_ENSEMBLE = "tree_ensemble"
    CLUSTERING = "clustering"
    FACTOR_ANALYSIS = "factor_analysis"
    TIME_SERIES = "time_series"


class ROCPoint(BaseModel):
    fpr: float
    tpr: float
    threshold: float


class LogisticRegressionOutput(BaseModel):
    coefficients: dict[str, float]
    odds_ratios: dict[str, float]
    ci_95_odds_ratios: dict[str, tuple[float, float]]
    p_values: dict[str, float]
    vif: dict[str, float]
    confusion_matrix: list[list[int]]
    roc_curve: list[ROCPoint]
    roc_auc: float
    youden_threshold: float
    mcfadden_pseudo_r2: float
    non_significant_variables: list[str]
    high_vif_variables: list[str]


class LinearRegressionOutput(BaseModel):
    coefficients: dict[str, float]
    ci_95: dict[str, tuple[float, float]]
    p_values: dict[str, float]
    r_squared: float
    r_squared_adj: float
    f_test_pvalue: float
    vif: dict[str, float]
    shapiro_pvalue: float
    breusch_pagan_pvalue: float
    durbin_watson: float
    influential_points_indices: list[int]
    rmse_train: float
    rmse_test: float
    mae_train: float
    mae_test: float


class TreeEnsembleOutput(BaseModel):
    feature_importance: dict[str, float]
    cv_scores_mean: float
    cv_scores_std: float
    train_score: float
    test_score: float
    overfitting_warning: bool
    hyperparameters: dict
    confusion_matrix: Optional[list[list[int]]] = None
    roc_curve: Optional[list[ROCPoint]] = None
    roc_auc: Optional[float] = None
    rmse: Optional[float] = None
    mae: Optional[float] = None
    r_squared: Optional[float] = None


class ClusteringOutput(BaseModel):
    n_clusters: int
    selection_method: str  # "elbow" | "silhouette"
    silhouette_score: float
    cluster_profiles: dict[str, dict[str, float]]
    pca_explained_variance_2d: tuple[float, float]


class FactorAnalysisOutput(BaseModel):
    explained_variance_ratio: list[float]
    n_axes_retained: int
    retention_rule: str  # "kaiser" | "elbow"
    contributions: dict[str, float]
    cos2: dict[str, float]


# ── Séries temporelles (ARIMA / SARIMA) ───────────────────────────────────────
# Schéma de sortie normatif, aligné sur la méthodologie SARIMA (étapes A–H).
# Couvre à la fois ARIMA (sans ordre saisonnier) et SARIMA (avec).
class TSCoefficient(BaseModel):
    nom: str
    valeur: float
    p_value: float


# NB : les champs périphériques ont des valeurs par défaut. La validation du
# schéma ne sert qu'à s'assurer d'une structure exploitable par le dashboard —
# la RIGUEUR statistique est portée par le prompt (méthodologie A–H) et par
# `statut`/`statut_final`, pas par l'obligation que le LLM remplisse chaque champ.
# Ainsi un résultat partiel mais utile est conservé et affiché au lieu d'être
# rejeté (le dashboard affiche « — » pour les champs absents).
class TSSerie(BaseModel):
    n_observations: Optional[int] = None
    frequence: Optional[str] = None
    saisonnalite_detectee: Optional[int] = None


class TSTransformation(BaseModel):
    log_applique: Optional[bool] = None
    justification: Optional[str] = None


class TSStationnarite(BaseModel):
    d: Optional[int] = None
    D: Optional[int] = None
    adf_p_value_finale: Optional[float] = None
    kpss_p_value_finale: Optional[float] = None


class TSModeleRetenu(BaseModel):
    type: str  # "ARIMA" | "SARIMA" | "AutoETS" | "AutoTheta" | ... — requis
    # Optionnel : le moteur de prévision automatique peut retenir un modèle sans
    # ordre (p,d,q) — ETS, Theta, SeasonalNaive. Forcer [0,0,0] mentirait sur la
    # nature du modèle retenu.
    ordre: Optional[list[int]] = None
    ordre_saisonnier: Optional[list[int]] = None  # [P, D, Q, s] ; None pour ARIMA
    aic: Optional[float] = None
    bic: Optional[float] = None
    coefficients: list[TSCoefficient] = []


class TSGate1(BaseModel):
    ljung_box_p_lag_s: Optional[float] = None
    ljung_box_p_lag_2s: Optional[float] = None
    jarque_bera_p: Optional[float] = None
    arch_p: Optional[float] = None
    statut: str  # "PASS" | "FAIL" | "NON_CALCULE" — requis (décision GATE 1)


class TSGate2(BaseModel):
    horizon_test: Optional[int] = None
    mape_pct: Optional[float] = None
    rmse: Optional[float] = None
    couverture_ic95_pct: Optional[float] = None
    statut: str  # "PASS" | "FAIL" | "NON_CALCULE" — requis (décision GATE 2)


class TSHistoPoint(BaseModel):
    date: str
    # Nullable : une observation manquante est légitime (trou dans la série) et
    # se représente en JSON par `null` — le graphique affiche alors une rupture.
    valeur: Optional[float] = None


class TSForecastPoint(BaseModel):
    date: str
    # Requis, lui : une prévision non finie est un échec du modèle, pas une
    # donnée manquante. La validation doit rejeter et relancer l'autocorrection.
    valeur_prevue: float
    ic_bas: Optional[float] = None
    ic_haut: Optional[float] = None


class TimeSeriesOutput(BaseModel):
    # Cœur requis : le modèle retenu, les deux décisions de gate, le statut final.
    modele_retenu: TSModeleRetenu
    gate_1_diagnostics_residus: TSGate1
    gate_2_validation_out_of_sample: TSGate2
    statut_final: str  # MODELE_VALIDE | MODELE_REJETE | INCERTITUDE_ELEVEE
    # Contexte (défauts tolérants) :
    serie: TSSerie = TSSerie()
    transformation: TSTransformation = TSTransformation()
    stationnarite: TSStationnarite = TSStationnarite()
    avertissements: list[str] = []
    historique: list[TSHistoPoint] = []
    prevision: list[TSForecastPoint] = []


class ModelSpec(BaseModel):
    family: ModelFamily
    required_outputs: list[str]
    output_schema: type[BaseModel]
    prompt_fragment: str
    diagnostic_checks: list[str]


MODEL_SPECS: dict[ModelFamily, ModelSpec] = {
    ModelFamily.LOGISTIC_REGRESSION: ModelSpec(
        family=ModelFamily.LOGISTIC_REGRESSION,
        required_outputs=list(LogisticRegressionOutput.model_fields.keys()),
        output_schema=LogisticRegressionOutput,
        prompt_fragment="""
MODELE ATTENDU : Régression Logistique.
OBLIGATION ABSOLUE : Tu dois générer un fichier "metrics.json" contenant EXACTEMENT ces clés (et aucune autre) :
- coefficients: dictionnaire (variable -> coef)
- odds_ratios: dictionnaire (variable -> exp(coef))
- ci_95_odds_ratios: dictionnaire (variable -> [lower, upper])
- p_values: dictionnaire (variable -> p-value)
- vif: dictionnaire (variable -> VIF)
- confusion_matrix: liste de liste d'entiers (matrice 2x2)
- roc_curve: liste d'objets avec "fpr", "tpr", "threshold"
- roc_auc: float
- youden_threshold: float
- mcfadden_pseudo_r2: float
- non_significant_variables: liste de strings (p_value > 0.05)
- high_vif_variables: liste de strings (VIF > 5)

Utilise statsmodels.api.Logit. Sauvegarde les visualisations générées avec matplotlib.
Tu DOIS sauvegarder ce JSON structuré avec : 
import json
with open('metrics.json', 'w') as f: json.dump(..., f)
""",
        diagnostic_checks=[]
    ),
    ModelFamily.LINEAR_REGRESSION: ModelSpec(
        family=ModelFamily.LINEAR_REGRESSION,
        required_outputs=list(LinearRegressionOutput.model_fields.keys()),
        output_schema=LinearRegressionOutput,
        prompt_fragment="""
MODELE ATTENDU : Régression Linéaire (OLS).
OBLIGATION ABSOLUE : Tu dois générer un fichier "metrics.json" contenant EXACTEMENT ces clés :
- coefficients
- ci_95
- p_values
- r_squared
- r_squared_adj
- f_test_pvalue
- vif
- shapiro_pvalue
- breusch_pagan_pvalue
- durbin_watson
- influential_points_indices
- rmse_train
- rmse_test
- mae_train
- mae_test

Sépare les données (80/20).
Utilise statsmodels.api.OLS. Sauvegarde les visualisations générées (ex: résidus) avec matplotlib.
Tu DOIS sauvegarder ce JSON structuré avec : 
import json
with open('metrics.json', 'w') as f: json.dump(metrics_dict, f)
""",
        diagnostic_checks=[]
    ),
    ModelFamily.TREE_ENSEMBLE: ModelSpec(
        family=ModelFamily.TREE_ENSEMBLE,
        required_outputs=list(TreeEnsembleOutput.model_fields.keys()),
        output_schema=TreeEnsembleOutput,
        prompt_fragment="""
MODELE ATTENDU : Arbres / Random Forest / Gradient Boosting.
OBLIGATION ABSOLUE : Tu dois générer un fichier "metrics.json" contenant EXACTEMENT ces clés :
- feature_importance
- cv_scores_mean
- cv_scores_std
- train_score
- test_score
- overfitting_warning (boolean, True si test_score << train_score)
- hyperparameters (dict)
(Si classification) : confusion_matrix, roc_curve (liste de {fpr, tpr, threshold}), roc_auc
(Si régression) : rmse, mae, r_squared

Sépare en train/test et fais une cross-validation k-fold (k=5) sur le train.
Tu DOIS sauvegarder ce JSON structuré avec : 
import json
with open('metrics.json', 'w') as f: json.dump(metrics_dict, f)
""",
        diagnostic_checks=[]
    ),
    ModelFamily.CLUSTERING: ModelSpec(
        family=ModelFamily.CLUSTERING,
        required_outputs=list(ClusteringOutput.model_fields.keys()),
        output_schema=ClusteringOutput,
        prompt_fragment="""
MODELE ATTENDU : Clustering (K-Means ou CAH).
OBLIGATION ABSOLUE : Tu dois générer un fichier "metrics.json" contenant EXACTEMENT ces clés :
- n_clusters (entier choisi)
- selection_method ("elbow" ou "silhouette")
- silhouette_score (float)
- cluster_profiles (dict : cluster_id -> {variable: moyenne})
- pca_explained_variance_2d (tuple de 2 floats)

Teste plusieurs valeurs de K, génère un graphique, et fais une PCA pour projeter en 2D.
Tu DOIS sauvegarder ce JSON structuré avec : 
import json
with open('metrics.json', 'w') as f: json.dump(metrics_dict, f)
""",
        diagnostic_checks=[]
    ),
    ModelFamily.FACTOR_ANALYSIS: ModelSpec(
        family=ModelFamily.FACTOR_ANALYSIS,
        required_outputs=list(FactorAnalysisOutput.model_fields.keys()),
        output_schema=FactorAnalysisOutput,
        prompt_fragment="""
MODELE ATTENDU : Analyse Factorielle (ACP / AFC / ACM).
OBLIGATION ABSOLUE : Tu dois générer un fichier "metrics.json" contenant EXACTEMENT ces clés :
- explained_variance_ratio (liste de floats)
- n_axes_retained (entier)
- retention_rule ("kaiser" ou "elbow")
- contributions (dict : variable -> float)
- cos2 (dict : variable -> float)

Justifie le nombre d'axes, trace le cercle des corrélations et la carte des individus.
Tu DOIS sauvegarder ce JSON structuré avec :
import json
with open('metrics.json', 'w') as f: json.dump(metrics_dict, f)
""",
        diagnostic_checks=[]
    ),
    ModelFamily.TIME_SERIES: ModelSpec(
        family=ModelFamily.TIME_SERIES,
        required_outputs=list(TimeSeriesOutput.model_fields.keys()),
        output_schema=TimeSeriesOutput,
        prompt_fragment="""
MODELE ATTENDU : Série temporelle univariée — ARIMA ou SARIMA (tu CHOISIS lequel selon les tests, voir Étape A/D).

Tu es un agent de modélisation de séries temporelles opérant dans un sandbox (statsmodels disponible). Tu DOIS suivre la méthodologie normative ci-dessous, étapes A à H, DANS L'ORDRE, sans en sauter aucune. Un code qui s'exécute n'est PAS un modèle validé : la validation repose sur GATE 1 (résidus = bruit blanc) ET GATE 2 (performance out-of-sample). Tu ne déclares "MODELE_VALIDE" que si GATE 1 ET GATE 2 sont PASS.

Utilise `statsmodels.tsa.statespace.sarimax.SARIMAX` (ARIMA = SARIMAX avec ordre saisonnier nul), `statsmodels.tsa.stattools.adfuller` et `kpss`, `statsmodels.stats.diagnostic.acorr_ljungbox` et `het_arch`, `scipy.stats.jarque_bera`.

[Étape A] Prétraitement & inventaire
- Identifie la colonne date et la colonne valeur (indiquées dans le contexte si fournies, sinon déduis-les). Parse les dates, trie, mets en index temporel avec fréquence explicite (pd.infer_freq ou déduction). Note n = nb d'observations et la saisonnalité candidate s (12 si mensuel, 7 si journalier hebdo, 4 si trimestriel…). Impute/signale les manquants.
- RÈGLE DE REFUS SAISONNIER : si n < 3*s, tu passes en ARIMA non-saisonnier (D=0, pas d'ordre saisonnier).

[Étape B] Stationnarité : applique ADF (H0=non-stationnaire, rejet si p<0.05) ET KPSS (H0=stationnaire, rejet si p<0.05). Décision croisée : ADF rejette & KPSS ne rejette pas → stationnaire ; sinon → différencier.

[Étape C] Transformation : régresse l'écart-type de chaque fenêtre saisonnière glissante sur sa moyenne. Si pente significativement positive (p<0.05) → applique log(y) (valeurs>0). Sinon garde l'échelle. Ne jamais logger par défaut.

[Étape D] Différenciation itérative pour (d, D) : pars de d=0,D=0 ; tant que non-stationnaire, applique une diff saisonnière (D+=1) si pics périodiques à des multiples de s sur l'ACF, sinon diff simple (d+=1). Garde-fou : stoppe si d+D>2 (ajoute un avertissement).

[Étape E] Sélection : grid search BORNÉ p,q,P,Q ∈ {0,1,2} (pour ARIMA, force P=Q=D=0). Fits en try/except avec enforce_stationarity=False, enforce_invertibility=False. Trie par AIC croissant, GARDE au maximum les 5 meilleurs (p,d,q,P,D,Q,s uniquement — voir hygiène mémoire ci-dessous). L'AIC ORDONNE, il ne VALIDE pas.
ATTENTION (ERREUR FRÉQUENTE : IndexError) : le nombre de fits qui réussissent (sans exception) peut être INFÉRIEUR à 5 (grille bornée, certaines combinaisons non stationnaires/non inversibles échouent). Ne suppose JAMAIS qu'il y a exactement 5 candidats : utilise un simple slicing `[:5]` sur la liste triée (qui renvoie automatiquement moins de 5 éléments si besoin, sans erreur) et itère uniquement avec `for cand in candidats_tries[:5]:` — n'accède JAMAIS à un candidat par un index fixe (ex. `candidats[4]`). Si AUCUN fit ne réussit, c'est une erreur fatale légitime à laisser remonter.
PERFORMANCE ET MÉMOIRE (sandbox à RAM limitée — CRITIQUE, respecte ceci scrupuleusement) :
- Pour CHAQUE fit du grid search : construis SARIMAX avec low_memory=True et appelle .fit(disp=False, maxiter=50, method='lbfgs').
- Ne conserve JAMAIS les 81 objets résultat en mémoire simultanément. Pendant la boucle du grid search, extrait uniquement (ordre, ordre_saisonnier, aic) dans une liste légère, PUIS supprime immédiatement l'objet fitté (`del result; del model`) avant l'itération suivante. N'appelle `gc.collect()` qu'une seule fois, après la boucle complète (jamais à l'intérieur — ça ralentirait chaque itération pour un gain mémoire négligeable tant que `del` est fait).
- Pour l'étape F (GATE 1), RE-FIT un par un chaque candidat du top 5 (dans l'ordre AIC), teste ses résidus, et si tu passes au candidat suivant, supprime le premier (`del`) avant de fitter le second. Ne garde en mémoire que le modèle actuellement testé.

[Étape F] GATE 1 (bloquant) — pour chaque candidat du meilleur au moins bon, calcule les tests sur les résidus EN EXCLUANT les (d + D*s) premières observations (période d'initialisation diffuse) :
- Ljung-Box aux lags s et 2*s → PASS si les deux p-values > 0.05
- Jarque-Bera (normalité, souhaitable) et test ARCH (hétéroscédasticité, p>0.05 souhaitable)
SI Ljung-Box échoue → candidat REJETÉ, passe au suivant. Le premier candidat qui passe est retenu.
GESTION OBLIGATOIRE DU CAS "AUCUN CANDIDAT NE PASSE" (ERREUR FRÉQUENTE : NameError sur la variable du candidat retenu si tu oublies ce cas) : AVANT la boucle, initialise explicitement une variable (ex. `candidat_retenu = None`) ET conserve à part les diagnostics résidus du TOUT PREMIER candidat testé (meilleur AIC), même s'il est rejeté. APRÈS la boucle : si `candidat_retenu is None` (aucun candidat n'a passé Ljung-Box), NE LÈVE AUCUNE EXCEPTION — retombe sur le premier candidat (meilleur AIC) comme `candidat_retenu` pour la suite (Étape G/H et modele_retenu dans metrics.json), avec gate_1 `statut="FAIL"` et un avertissement dans `avertissements`. Le pipeline doit TOUJOURS pouvoir continuer jusqu'à metrics.json, même quand GATE 1 échoue pour tous les candidats.

[Étape G] GATE 2 (bloquant) — réserve les min(12..24, 20% de n) dernières obs comme test (jamais vues). Ré-estime le modèle retenu sur le train, prévois l'horizon de test avec IC 95%. Calcule MAPE%, RMSE, et taux de couverture de l'IC95. RÈGLE : si MAPE>20% OU couverture<70% → statut GATE 2 = FAIL. Sinon PASS.

[Étape H] Si GATE 1 et GATE 2 PASS : ré-estime le modèle final sur TOUTE la série, produis la prévision future (horizon indiqué dans le contexte, défaut = s périodes) avec IC95. Trace UN graphique matplotlib : historique + prévision + bande IC95 (plt.savefig non requis, la figure est capturée automatiquement — ne PAS appeler plt.show()).

OBLIGATION ABSOLUE — génère un fichier "metrics.json" avec EXACTEMENT ces clés (respecte les types) :
- serie: {"n_observations": int, "frequence": str, "saisonnalite_detectee": int|null}
- transformation: {"log_applique": bool, "justification": str}
- stationnarite: {"d": int, "D": int, "adf_p_value_finale": float, "kpss_p_value_finale": float}
- modele_retenu: {"type": "ARIMA"|"SARIMA", "ordre": [p,d,q], "ordre_saisonnier": [P,D,Q,s]|null, "aic": float, "bic": float, "coefficients": [{"nom": str, "valeur": float, "p_value": float}]}
- gate_1_diagnostics_residus: {"ljung_box_p_lag_s": float, "ljung_box_p_lag_2s": float, "jarque_bera_p": float, "arch_p": float, "statut": "PASS"|"FAIL"}
- gate_2_validation_out_of_sample: {"horizon_test": int, "mape_pct": float, "rmse": float, "couverture_ic95_pct": float, "statut": "PASS"|"FAIL"}
- statut_final: "MODELE_VALIDE" | "MODELE_REJETE" | "INCERTITUDE_ELEVEE"  (JAMAIS "MODELE_VALIDE" si un gate est FAIL)
- avertissements: [str]
- historique: [{"date": "YYYY-MM-DD", "valeur": float}]  (série observée, sur l'échelle ORIGINALE même si log appliqué)
- prevision: [{"date": "YYYY-MM-DD", "valeur_prevue": float, "ic_bas": float, "ic_haut": float}]  (prévision future finale, échelle ORIGINALE)

Si aucun candidat ne passe les gates après les 5, mets statut_final="INCERTITUDE_ELEVEE" ou "MODELE_REJETE", remplis quand même le reste au mieux, et ajoute un avertissement clair.
Écris chaque résultat numérique au fur et à mesure via print().

ERREUR FRÉQUENTE À NE PAS COMMETTRE : la clé "statut" ("PASS"/"FAIL") de gate_1_diagnostics_residus ET de gate_2_validation_out_of_sample est OBLIGATOIRE — ce n'est PAS optionnel, ne l'oublie JAMAIS, même si tu ne calcules pas tous les diagnostics secondaires (jarque_bera_p, arch_p). Utilise EXACTEMENT ce squelette pour construire et sauvegarder metrics_dict (adapte les valeurs, ne change PAS les noms de clés) :

metrics_dict = {
    "serie": {"n_observations": n, "frequence": freq_str, "saisonnalite_detectee": s_detectee},
    "transformation": {"log_applique": log_applique, "justification": justification_str},
    "stationnarite": {"d": d, "D": D, "adf_p_value_finale": adf_p, "kpss_p_value_finale": kpss_p},
    "modele_retenu": {
        "type": "SARIMA",  # ou "ARIMA"
        "ordre": [p, d, q],
        "ordre_saisonnier": [P, D, Q, s],  # ou None si ARIMA
        "aic": aic_val, "bic": bic_val,
        "coefficients": [{"nom": nom, "valeur": val, "p_value": pval} for nom, val, pval in coefs],
    },
    "gate_1_diagnostics_residus": {
        "ljung_box_p_lag_s": lb_p_s, "ljung_box_p_lag_2s": lb_p_2s,
        "jarque_bera_p": jb_p, "arch_p": arch_p,
        "statut": "PASS" if (lb_p_s > 0.05 and lb_p_2s > 0.05) else "FAIL",  # CLÉ OBLIGATOIRE
    },
    "gate_2_validation_out_of_sample": {
        "horizon_test": horizon_test, "mape_pct": mape, "rmse": rmse, "couverture_ic95_pct": couverture,
        "statut": "PASS" if (mape <= 20 and couverture >= 70) else "FAIL",  # CLÉ OBLIGATOIRE
    },
    "statut_final": "MODELE_VALIDE",  # cohérent avec les deux statuts ci-dessus, voir règle plus haut
    "avertissements": [],
    "historique": [{"date": d.strftime("%Y-%m-%d"), "valeur": float(v)} for d, v in serie_observee.items()],
    "prevision": [{"date": d.strftime("%Y-%m-%d"), "valeur_prevue": float(v), "ic_bas": float(lo), "ic_haut": float(hi)} for d, v, lo, hi in prevision_finale],
}
import json
with open('metrics.json', 'w') as f:
    json.dump(metrics_dict, f)
""",
        diagnostic_checks=[]
    )
}
