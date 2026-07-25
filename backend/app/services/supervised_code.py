"""supervised_code.py — Script déterministe du tournoi supervisé, exécuté en sandbox.

Volontairement déterministe, comme le moteur de prévision automatique : le code
n'est pas généré par un LLM, il n'y a donc rien à autocorriger. La « reprise
jusqu'à ce que les résultats soient bons » n'est pas une régénération au hasard
mais une **échelle de remédiation** — chaque échec d'hypothèse désigne le modèle
suivant à essayer.

Le script s'arrête dès qu'un modèle satisfait toutes les normes (hypothèses
bloquantes + performances), sans consommer le budget restant.
"""

from app.services.supervised_specs import (
    ALPHA, BUDGET_SECONDES, DW_MAX, DW_MIN, ECART_SURAPPRENTISSAGE, EPV_MIN,
    GAIN_RMSE_MIN, MCC_MIN_UTILE, QUALITE_MCC, QUALITE_R2, R2_MIN_UTILE, SEUIL_DESEQUILIBRE,
    VIF_AVERTISSEMENT, VIF_BLOQUANT,
)

# Chaque diagnostic est isolé : un test qui échoue se dégrade en "NON_CALCULE"
# plutôt que de faire tomber tout le tournoi.
_TEMPLATE = '''
import json, math, time, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

TARGET = {target!r}
FEATURES = {features!r}
BUDGET = {budget}
SEUIL_DESEQUILIBRE = {seuil_desequilibre}
VIF_AVERT, VIF_BLOQ = {vif_avert}, {vif_bloq}
ALPHA = {alpha}
DW_MIN, DW_MAX = {dw_min}, {dw_max}
EPV_MIN = {epv_min}
ECART_SURAPP = {ecart_surapp}
R2_MIN_UTILE = {r2_min}
GAIN_RMSE_MIN = {gain_rmse}
MCC_MIN_UTILE = {mcc_min}
QUALITE_R2 = {qualite_r2!r}
QUALITE_MCC = {qualite_mcc!r}

def qualifier(valeur, echelle):
    """Niveau de qualite atteint. Un seuil franchi n'est pas un gage de qualite :
    on dit ou se situe le modele, l'utilisateur juge si c'est suffisant pour son
    usage."""
    if valeur is None:
        return "inconnue"
    for seuil, libelle in echelle:
        if valeur >= seuil:
            return libelle
    return "insuffisante"

DEPART = time.time()
def reste():
    return BUDGET - (time.time() - DEPART)

def f(x):
    """Flottant sérialisable en JSON (NaN/inf -> None)."""
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None

# ── Préparation ──────────────────────────────────────────────────────────────
data = df.copy()
colonnes = [c for c in FEATURES if c in data.columns]
if TARGET not in data.columns:
    raise ValueError("Colonne cible '%s' absente du jeu de donnees." % TARGET)

data = data[colonnes + [TARGET]].dropna()
if len(data) < 30:
    raise ValueError("Trop peu de lignes exploitables (%d) apres suppression des manquants." % len(data))

y_brut = data[TARGET]
X_brut = data[colonnes]

# Encodage : one-hot pour les catégorielles, sans colonne de référence redondante
# (drop_first) qui gonflerait artificiellement le VIF.
X = pd.get_dummies(X_brut, drop_first=True)
X = X.loc[:, X.nunique() > 1]              # colonnes constantes : inutiles et VIF infini
X = X.astype(float)
if X.shape[1] == 0:
    raise ValueError("Aucune variable explicative exploitable apres encodage.")

# ── Détection automatique de la famille ──────────────────────────────────────
est_numerique = pd.api.types.is_numeric_dtype(y_brut)
n_modalites = y_brut.nunique()
# Une cible numérique à peu de modalités est en réalité catégorielle (0/1, notes).
if est_numerique and n_modalites > 20:
    famille = "regression"
    y = y_brut.astype(float)
    classes = None
    ratio_minoritaire = None
else:
    codes, classes = pd.factorize(y_brut)
    y = pd.Series(codes, index=y_brut.index)
    parts = y.value_counts(normalize=True)
    ratio_minoritaire = float(parts.min())
    famille = ("classification_desequilibree"
               if ratio_minoritaire < SEUIL_DESEQUILIBRE else "classification")
    classes = [str(c) for c in classes]

from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold, KFold

stratify = y if famille != "regression" and y.value_counts().min() >= 2 else None
X_tr, X_te, y_tr, y_te = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=stratify
)

# ── Diagnostics d'hypothèses ─────────────────────────────────────────────────
def calcul_vif(Xd):
    """VIF par variable. Au-delà de VIF_BLOQ, les coefficients ne sont plus
    interprétables : deux variables portent la même information."""
    try:
        from statsmodels.stats.outliers_influence import variance_inflation_factor
        import statsmodels.api as sm
        Xc = sm.add_constant(Xd, has_constant="add")
        vals = {{}}
        for i, nom in enumerate(Xc.columns):
            if nom == "const":
                continue
            vals[nom] = f(variance_inflation_factor(Xc.values, i))
        return vals
    except Exception:
        return {{}}

def diagnostics_regression(res, Xd, yd):
    """Diagnostics OLS : le coeur du contrat statistique."""
    d = {{}}
    residus = np.asarray(res.resid, dtype=float)

    # Normalité — INFORMATIVE : Shapiro rejette quasi systematiquement des n>500
    # sans que le modele soit pour autant inexploitable.
    try:
        from scipy import stats as st
        if len(residus) <= 5000:
            d["normalite_p"] = f(st.shapiro(residus).pvalue)
            d["normalite_test"] = "shapiro"
        else:
            import statsmodels.api as sm
            d["normalite_p"] = f(sm.stats.stattools.jarque_bera(residus)[1])
            d["normalite_test"] = "jarque_bera"
    except Exception:
        d["normalite_p"], d["normalite_test"] = None, "NON_CALCULE"

    # Homoscedasticite — REMEDIEE : si violee on passe en erreurs-types HC3.
    try:
        from statsmodels.stats.diagnostic import het_breuschpagan, het_white
        d["breusch_pagan_p"] = f(het_breuschpagan(residus, res.model.exog)[1])
        try:
            d["white_p"] = f(het_white(residus, res.model.exog)[1])
        except Exception:
            d["white_p"] = None
    except Exception:
        d["breusch_pagan_p"], d["white_p"] = None, None

    # Independance des residus — BLOQUANTE si franchement hors [DW_MIN, DW_MAX].
    try:
        from statsmodels.stats.stattools import durbin_watson
        d["durbin_watson"] = f(durbin_watson(residus))
    except Exception:
        d["durbin_watson"] = None

    # Linearite (RESET de Ramsey) — BLOQUANTE : une relation non lineaire rend
    # les coefficients OLS trompeurs.
    try:
        from statsmodels.stats.diagnostic import linear_reset
        d["reset_p"] = f(linear_reset(res, power=2, use_f=True).pvalue)
    except Exception:
        d["reset_p"] = None

    # Points influents — INFORMATIVE : listes, jamais supprimes d'office.
    try:
        from statsmodels.stats.outliers_influence import OLSInfluence
        cook = OLSInfluence(res).cooks_distance[0]
        seuil = 4.0 / len(cook)
        idx = np.where(cook > seuil)[0]
        d["points_influents"] = [int(i) for i in idx[:50]]
        d["n_points_influents"] = int(len(idx))
        d["seuil_cook"] = f(seuil)
    except Exception:
        d["points_influents"], d["n_points_influents"] = [], 0

    d["vif"] = calcul_vif(Xd)
    return d

def separation_complete(Xd, yd):
    """Une variable qui separe parfaitement les classes fait diverger les
    coefficients logistiques vers l'infini : le modele devient ininterpretable."""
    try:
        for col in Xd.columns:
            for classe in np.unique(yd):
                v0 = Xd.loc[yd == classe, col]
                v1 = Xd.loc[yd != classe, col]
                if len(v0) and len(v1) and (v0.max() < v1.min() or v0.min() > v1.max()):
                    return True, col
    except Exception:
        pass
    return False, None

# ── Modèles du tournoi ───────────────────────────────────────────────────────
def eval_regression(nom, libelle):
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    info = {{"modele": nom, "libelle": libelle, "hypotheses": {{}}, "performances": {{}}}}

    if nom == "ols":
        import statsmodels.api as sm
        Xc = sm.add_constant(X_tr, has_constant="add")
        res = sm.OLS(y_tr.values, Xc.values).fit()
        diag = diagnostics_regression(res, X_tr, y_tr)

        # Remediation automatique de l'heteroscedasticite : erreurs-types robustes.
        bp = diag.get("breusch_pagan_p")
        if bp is not None and bp < ALPHA:
            res = sm.OLS(y_tr.values, Xc.values).fit(cov_type="HC3")
            info["remediation"] = "Erreurs-types robustes HC3 (heteroscedasticite detectee)."

        noms = ["const"] + list(X_tr.columns)
        info["coefficients"] = {{n: f(v) for n, v in zip(noms, res.params)}}
        info["p_values"] = {{n: f(v) for n, v in zip(noms, res.pvalues)}}
        try:
            ic = res.conf_int()
            info["ic_95"] = {{n: [f(ic[i][0]), f(ic[i][1])] for i, n in enumerate(noms)}}
        except Exception:
            info["ic_95"] = {{}}
        info["r_squared"] = f(res.rsquared)
        info["r_squared_adj"] = f(res.rsquared_adj)
        info["f_test_p"] = f(res.f_pvalue)
        info["variables_non_significatives"] = [
            n for n, p in info["p_values"].items() if p is not None and p > ALPHA and n != "const"
        ]
        info["hypotheses"] = diag
        pred_tr = res.predict(Xc.values)
        pred_te = res.predict(sm.add_constant(X_te, has_constant="add").values)
    else:
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        if nom == "elasticnet":
            from sklearn.linear_model import ElasticNetCV
            est = make_pipeline(
                StandardScaler(),
                ElasticNetCV(l1_ratio=[0.1, 0.5, 0.7, 0.9, 0.95, 1.0], cv=5,
                             random_state=42, max_iter=5000),
            )
        else:
            from sklearn.ensemble import HistGradientBoostingRegressor
            est = HistGradientBoostingRegressor(random_state=42)
        est.fit(X_tr, y_tr)
        pred_tr, pred_te = est.predict(X_tr), est.predict(X_te)
        if nom == "elasticnet":
            enet = est[-1]
            info["alpha"] = f(enet.alpha_)
            info["l1_ratio"] = f(enet.l1_ratio_)
            info["coefficients"] = {{c: f(v) for c, v in zip(X_tr.columns, enet.coef_)}}
        else:
            try:
                from sklearn.inspection import permutation_importance
                imp = permutation_importance(est, X_te, y_te, n_repeats=5, random_state=42)
                info["importances"] = {{c: f(v) for c, v in zip(X_tr.columns, imp.importances_mean)}}
            except Exception:
                info["importances"] = {{}}
        # Les modeles non parametriques n'ont pas d'hypothese distributionnelle,
        # mais la multicolinearite reste utile a signaler pour l'interpretation.
        info["hypotheses"] = {{"vif": calcul_vif(X_tr)}}

    # Baseline : predire la moyenne. Un modele qui ne fait pas mieux est inutile.
    base = np.full(len(y_te), float(np.mean(y_tr)))
    info["performances"] = {{
        "r2_train": f(r2_score(y_tr, pred_tr)),
        "r2_test": f(r2_score(y_te, pred_te)),
        "rmse_train": f(math.sqrt(mean_squared_error(y_tr, pred_tr))),
        "rmse_test": f(math.sqrt(mean_squared_error(y_te, pred_te))),
        "mae_train": f(mean_absolute_error(y_tr, pred_tr)),
        "mae_test": f(mean_absolute_error(y_te, pred_te)),
        "rmse_baseline": f(math.sqrt(mean_squared_error(y_te, base))),
    }}
    return info

def eval_classification(nom, libelle, ponderee):
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score, f1_score,
                                 matthews_corrcoef, confusion_matrix, roc_auc_score,
                                 roc_curve, average_precision_score, precision_recall_curve)
    info = {{"modele": nom, "libelle": libelle, "hypotheses": {{}}, "performances": {{}}}}
    poids = "balanced" if ponderee else None
    binaire = int(pd.Series(y).nunique()) == 2

    if nom.startswith("logistique"):
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        # EPV : evenements par variable. En dessous de EPV_MIN les coefficients
        # sont instables — on passe alors en logistique penalisee (L2 fort).
        n_evenements = int(pd.Series(y_tr).value_counts().min())
        epv = n_evenements / max(X_tr.shape[1], 1)
        sep, col_sep = separation_complete(X_tr, y_tr)
        info["hypotheses"]["epv"] = f(epv)
        info["hypotheses"]["separation_complete"] = bool(sep)
        info["hypotheses"]["variable_separatrice"] = col_sep
        info["hypotheses"]["vif"] = calcul_vif(X_tr)

        penalise = sep or epv < EPV_MIN
        C = 0.1 if penalise else 1.0
        if penalise:
            info["remediation"] = (
                "Logistique penalisee L2 (C=0.1) : "
                + ("separation complete detectee" if sep else "EPV insuffisant (%.1f)" % epv)
                + "."
            )
        est = make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, class_weight=poids, C=C, random_state=42),
        )
        est.fit(X_tr, y_tr)
        try:
            info["coefficients"] = {{c: f(v) for c, v in zip(X_tr.columns, est[-1].coef_[0])}}
            info["odds_ratios"] = {{c: f(math.exp(v)) for c, v in info["coefficients"].items()
                                   if v is not None and abs(v) < 700}}
        except Exception:
            pass
    elif nom == "balanced_random_forest":
        from imblearn.ensemble import BalancedRandomForestClassifier
        est = BalancedRandomForestClassifier(
            n_estimators=300, random_state=42, sampling_strategy="all", replacement=True,
        )
        est.fit(X_tr, y_tr)
        info["importances"] = {{c: f(v) for c, v in zip(X_tr.columns, est.feature_importances_)}}
    elif nom == "random_forest":
        from sklearn.ensemble import RandomForestClassifier
        est = RandomForestClassifier(n_estimators=300, random_state=42, class_weight=poids)
        est.fit(X_tr, y_tr)
        info["importances"] = {{c: f(v) for c, v in zip(X_tr.columns, est.feature_importances_)}}
    else:
        from sklearn.ensemble import HistGradientBoostingClassifier
        est = HistGradientBoostingClassifier(
            random_state=42, class_weight=("balanced" if ponderee else None),
        )
        est.fit(X_tr, y_tr)
        try:
            from sklearn.inspection import permutation_importance
            imp = permutation_importance(est, X_te, y_te, n_repeats=5, random_state=42)
            info["importances"] = {{c: f(v) for c, v in zip(X_tr.columns, imp.importances_mean)}}
        except Exception:
            info["importances"] = {{}}

    proba_te = None
    try:
        proba_te = est.predict_proba(X_te)
    except Exception:
        pass

    seuil = 0.5
    if ponderee and binaire and proba_te is not None:
        # Sur donnees desequilibrees, 0.5 est arbitraire : on prend le seuil qui
        # maximise le F1 sur la courbe precision-rappel.
        try:
            prec, rec, seuils = precision_recall_curve(y_te, proba_te[:, 1])
            f1s = np.divide(2 * prec * rec, prec + rec,
                            out=np.zeros_like(prec), where=(prec + rec) > 0)
            if len(seuils):
                seuil = float(seuils[int(np.argmax(f1s[:-1]))])
        except Exception:
            pass

    if binaire and proba_te is not None:
        pred_te = (proba_te[:, 1] >= seuil).astype(int)
    else:
        pred_te = est.predict(X_te)
    pred_tr = est.predict(X_tr)
    info["seuil_decision"] = f(seuil)

    perf = {{
        "accuracy_train": f(accuracy_score(y_tr, pred_tr)),
        "accuracy_test": f(accuracy_score(y_te, pred_te)),
        "balanced_accuracy": f(balanced_accuracy_score(y_te, pred_te)),
        "f1": f(f1_score(y_te, pred_te, average="binary" if binaire else "macro")),
        "mcc": f(matthews_corrcoef(y_te, pred_te)),
    }}
    # Baseline : toujours predire la classe majoritaire.
    majoritaire = int(pd.Series(y_tr).value_counts().idxmax())
    perf["accuracy_baseline"] = f(accuracy_score(y_te, np.full(len(y_te), majoritaire)))

    if proba_te is not None and binaire:
        try:
            perf["roc_auc"] = f(roc_auc_score(y_te, proba_te[:, 1]))
            fpr, tpr, thr = roc_curve(y_te, proba_te[:, 1])
            pas = max(1, len(fpr) // 100)
            info["roc_curve"] = [
                {{"fpr": f(a), "tpr": f(b), "threshold": f(c)}}
                for a, b, c in zip(fpr[::pas], tpr[::pas], thr[::pas])
            ]
            perf["pr_auc"] = f(average_precision_score(y_te, proba_te[:, 1]))
            prec_c, rec_c, _ = precision_recall_curve(y_te, proba_te[:, 1])
            pas_pr = max(1, len(prec_c) // 100)
            info["pr_curve"] = [
                {{"recall": f(rc), "precision": f(pc)}}
                for pc, rc in zip(prec_c[::pas_pr], rec_c[::pas_pr])
            ]
            # Ligne de base d'une courbe PR : la prévalence de la classe positive.
            # Sans elle, une PR-AUC de 0,4 est illisible (excellente si la classe
            # pèse 5 %, mediocre si elle pèse 50 %).
            perf["prevalence_positive"] = f(float(np.mean(y_te == 1)))
        except Exception:
            pass
    elif proba_te is not None:
        try:
            perf["roc_auc"] = f(roc_auc_score(y_te, proba_te, multi_class="ovr"))
        except Exception:
            pass

    try:
        info["confusion_matrix"] = [[int(v) for v in ligne]
                                    for ligne in confusion_matrix(y_te, pred_te)]
    except Exception:
        pass
    info["performances"] = perf
    return info

# ── Verdict : hypotheses bloquantes + performances ───────────────────────────
def verdict(info, famille):
    """Un modele n'est valide que si AUCUNE hypothese bloquante n'est violee ET
    que ses performances battent la baseline sans surapprentissage."""
    violations, avertissements = [], []
    h = info.get("hypotheses") or {{}}
    p = info.get("performances") or {{}}

    vif = h.get("vif") or {{}}
    hauts = [k for k, v in vif.items() if v is not None and v > VIF_BLOQ]
    moyens = [k for k, v in vif.items() if v is not None and VIF_AVERT < v <= VIF_BLOQ]
    if hauts:
        violations.append("Multicolinearite severe (VIF > %g) : %s" % (VIF_BLOQ, ", ".join(hauts[:6])))
    if moyens:
        avertissements.append("Multicolinearite moderee (VIF > %g) : %s" % (VIF_AVERT, ", ".join(moyens[:6])))

    if info["modele"] == "ols":
        if h.get("reset_p") is not None and h["reset_p"] < ALPHA:
            violations.append("Relation non lineaire (RESET p=%.4g) : les coefficients OLS sont trompeurs." % h["reset_p"])
        dw = h.get("durbin_watson")
        if dw is not None and not (DW_MIN <= dw <= DW_MAX):
            violations.append("Residus autocorreles (Durbin-Watson=%.2f) : les intervalles de confiance sont invalides." % dw)
        if h.get("normalite_p") is not None and h["normalite_p"] < ALPHA:
            avertissements.append("Normalite des residus rejetee (p=%.4g) — informatif, n'invalide pas le modele." % h["normalite_p"])
        if h.get("n_points_influents"):
            avertissements.append("%d point(s) influent(s) (distance de Cook) — signales, non supprimes." % h["n_points_influents"])

    if info["modele"].startswith("logistique"):
        if h.get("separation_complete") and not info.get("remediation"):
            violations.append("Separation complete par '%s'." % h.get("variable_separatrice"))
        if h.get("epv") is not None and h["epv"] < EPV_MIN and not info.get("remediation"):
            violations.append("Evenements par variable insuffisants (EPV=%.1f < %d)." % (h["epv"], EPV_MIN))

    # ── Performances ──
    if famille == "regression":
        r2 = p.get("r2_test")
        rmse, base_rmse = p.get("rmse_test"), p.get("rmse_baseline")
        gain = ((base_rmse - rmse) / base_rmse) if (rmse and base_rmse) else None
        if r2 is None or r2 < R2_MIN_UTILE:
            violations.append(
                "Apport negligeable : R2 test=%s (< %.2f attendu) — le modele n'explique "
                "pratiquement rien de plus que la moyenne."
                % ("n/a" if r2 is None else "%.3f" % r2, R2_MIN_UTILE)
            )
        elif gain is not None and gain < GAIN_RMSE_MIN:
            violations.append(
                "Gain insuffisant sur la baseline : RMSE ameliore de %.1f%% seulement (< %.0f%% attendu)."
                % (gain * 100, GAIN_RMSE_MIN * 100)
            )
        tr, te = p.get("r2_train"), p.get("r2_test")
        if tr and te is not None and tr > 0 and (tr - te) / abs(tr) > ECART_SURAPP:
            violations.append("Surapprentissage : R2 train=%.3f vs test=%.3f." % (tr, te))
    else:
        mcc = p.get("mcc")
        if mcc is None or mcc < MCC_MIN_UTILE:
            violations.append(
                "Association negligeable : MCC=%s (< %.2f attendu) — le modele ne fait "
                "guere mieux que le hasard."
                % ("n/a" if mcc is None else "%.3f" % mcc, MCC_MIN_UTILE)
            )
        acc, base = p.get("accuracy_test"), p.get("accuracy_baseline")
        if acc is not None and base is not None and acc <= base and (mcc or 0) <= 0:
            violations.append("Le modele ne bat pas la classe majoritaire (%.3f vs %.3f)." % (acc, base))
        tr, te = p.get("accuracy_train"), p.get("accuracy_test")
        if tr and te is not None and tr > 0 and (tr - te) / tr > ECART_SURAPP:
            violations.append("Surapprentissage : accuracy train=%.3f vs test=%.3f." % (tr, te))

    if famille == "regression":
        info["qualite"] = qualifier(p.get("r2_test"), QUALITE_R2)
        info["metrique_qualite"] = "R2 test"
    else:
        info["qualite"] = qualifier(p.get("mcc"), QUALITE_MCC)
        info["metrique_qualite"] = "MCC"

    info["violations"] = violations
    info["avertissements"] = avertissements
    info["conforme"] = len(violations) == 0
    return info

# ── Artefact déployable ──────────────────────────────────────────────────────
def pipeline_deployable(nom, famille, ponderee, info):
    """Réajuste le modèle retenu en pipeline auto-suffisant, encodage compris.

    Le tournoi travaille sur X déjà encodé en one-hot ; un tel estimateur est
    inutilisable tel quel (il faudrait rejouer l'encodage à la main, avec le même
    ordre de colonnes). On reconstruit donc un Pipeline qui accepte les colonnes
    BRUTES : c'est lui qui part dans le .pkl et que la simulation interroge.

    `handle_unknown="ignore"` : une modalité jamais vue en apprentissage doit
    donner une prédiction dégradée, pas une exception.
    """
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    num = [c for c in X_brut.columns if pd.api.types.is_numeric_dtype(X_brut[c])]
    cat = [c for c in X_brut.columns if c not in num]
    try:
        encodeur = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:  # scikit-learn < 1.2
        encodeur = OneHotEncoder(handle_unknown="ignore", sparse=False)

    pre = ColumnTransformer(
        [("num", StandardScaler(), num), ("cat", encodeur, cat)],
        remainder="drop",
    )
    poids = "balanced" if ponderee else None

    if famille == "regression":
        if nom == "ols":
            # LinearRegression donne les mêmes coefficients qu'OLS ; statsmodels
            # n'était là que pour l'inférence (p-values, IC, diagnostics).
            from sklearn.linear_model import LinearRegression
            est = LinearRegression()
        elif nom == "elasticnet":
            from sklearn.linear_model import ElasticNetCV
            est = ElasticNetCV(l1_ratio=[0.1, 0.5, 0.7, 0.9, 0.95, 1.0], cv=5,
                               random_state=42, max_iter=5000)
        else:
            from sklearn.ensemble import HistGradientBoostingRegressor
            est = HistGradientBoostingRegressor(random_state=42)
    elif nom.startswith("logistique"):
        from sklearn.linear_model import LogisticRegression
        C = 0.1 if info.get("remediation") else 1.0
        est = LogisticRegression(max_iter=2000, class_weight=poids, C=C, random_state=42)
    elif nom == "balanced_random_forest":
        from imblearn.ensemble import BalancedRandomForestClassifier
        est = BalancedRandomForestClassifier(
            n_estimators=300, random_state=42, sampling_strategy="all", replacement=True)
    elif nom == "random_forest":
        from sklearn.ensemble import RandomForestClassifier
        est = RandomForestClassifier(n_estimators=300, random_state=42, class_weight=poids)
    else:
        from sklearn.ensemble import HistGradientBoostingClassifier
        est = HistGradientBoostingClassifier(
            random_state=42, class_weight=("balanced" if ponderee else None))

    pipe = Pipeline([("pretraitement", pre), ("modele", est)])
    # Réajusté sur TOUTES les données : les métriques viennent du split test, mais
    # le modèle livré doit exploiter l'ensemble de l'information disponible.
    pipe.fit(X_brut.loc[y.index], y)
    return pipe, num, cat


# ── Tournoi ──────────────────────────────────────────────────────────────────
MODELES = {modeles!r}
CLE_TRI = {{"regression": "r2_test", "classification": "roc_auc",
            "classification_desequilibree": "mcc"}}[famille]

candidats, retenu = [], None
for nom, libelle in MODELES[famille]:
    if reste() <= 5:
        break
    try:
        if famille == "regression":
            info = eval_regression(nom, libelle)
        else:
            info = eval_classification(
                nom, libelle, ponderee=(famille == "classification_desequilibree")
            )
        info = verdict(info, famille)
    except Exception as exc:
        info = {{"modele": nom, "libelle": libelle, "erreur": "%s: %s" % (type(exc).__name__, exc),
                 "conforme": False, "violations": ["Execution impossible."],
                 "avertissements": [], "performances": {{}}, "hypotheses": {{}}}}
    candidats.append(info)

    # Sortie anticipee : le premier modele qui satisfait TOUTES les normes est
    # livre sans consommer le budget restant.
    if info.get("conforme"):
        retenu = info
        break

def score(c):
    v = (c.get("performances") or {{}}).get(CLE_TRI)
    return v if v is not None else -1e18

if retenu is None and candidats:
    conformes = [c for c in candidats if c.get("conforme")]
    retenu = max(conformes or candidats, key=score)

if retenu is None:
    raise ValueError("Aucun modele n'a pu etre evalue.")

perf_retenu = retenu.get("performances") or {{}}
if famille == "regression":
    utile = (perf_retenu.get("r2_test") or -1) >= R2_MIN_UTILE
else:
    utile = (perf_retenu.get("mcc") or -1) >= MCC_MIN_UTILE

if retenu.get("conforme"):
    statut = "MODELE_VALIDE"
elif not utile:
    # Aucune remediation ne rattrape un modele sans pouvoir predictif : le dire
    # franchement vaut mieux que livrer un modele decoratif.
    statut = "AUCUN_MODELE_UTILE"
else:
    statut = "HYPOTHESES_VIOLEES"

metrics = {{
    "famille": famille,
    "cible": TARGET,
    "variables": list(X.columns),
    "n_observations": int(len(data)),
    "n_train": int(len(X_tr)),
    "n_test": int(len(X_te)),
    "classes": classes,
    "ratio_minoritaire": f(ratio_minoritaire) if ratio_minoritaire is not None else None,
    "metrique_selection": CLE_TRI,
    "modele_retenu": retenu,
    "candidats": candidats,
    "statut_final": statut,
    "qualite": retenu.get("qualite"),
    "metrique_qualite": retenu.get("metrique_qualite"),
    "budget_secondes": BUDGET,
    "duree_secondes": f(time.time() - DEPART),
    "sortie_anticipee": bool(retenu.get("conforme") and len(candidats) < len(MODELES[famille])),
    "avertissements": list(retenu.get("avertissements") or []),
    "violations": list(retenu.get("violations") or []),
}}

# Artefact déployable : le runner du sandbox récupère automatiquement les .pkl.
try:
    import joblib
    ponderee_finale = (famille == "classification_desequilibree")
    pipe, cols_num, cols_cat = pipeline_deployable(
        retenu["modele"], famille, ponderee_finale, retenu)
    joblib.dump(pipe, "modele.pkl")
    metrics_extra = {{
        "artefact": {{
            "disponible": True,
            "colonnes_attendues": list(X_brut.columns),
            "colonnes_numeriques": cols_num,
            "colonnes_categorielles": cols_cat,
            "modalites": {{
                c: [str(v) for v in sorted(X_brut[c].dropna().unique())[:50]]
                for c in cols_cat
            }},
            "bornes_numeriques": {{
                c: {{"min": f(X_brut[c].min()), "max": f(X_brut[c].max()),
                     "median": f(X_brut[c].median())}}
                for c in cols_num
            }},
            "classes": classes,
            "seuil_decision": retenu.get("seuil_decision"),
        }}
    }}
    with open("modele_metadata.json", "w", encoding="utf-8") as fh:
        json.dump(metrics_extra["artefact"], fh, ensure_ascii=False, default=str)
except Exception as exc:
    metrics_extra = {{"artefact": {{"disponible": False, "raison": str(exc)}}}}

metrics.update(metrics_extra)

with open("metrics.json", "w", encoding="utf-8") as fh:
    json.dump(metrics, fh, ensure_ascii=False, default=str)

print("Famille : %s | modele retenu : %s | statut : %s | qualite : %s" % (famille, retenu["libelle"], statut, retenu.get("qualite")))
print("Candidats evalues : %d/%d en %.1f s" % (len(candidats), len(MODELES[famille]), time.time() - DEPART))
'''


def build_supervised_code(target: str, features: list[str], budget: int | None = None) -> str:
    """Rend le script du tournoi, prêt à être exécuté dans le sandbox."""
    from app.services.supervised_specs import MODELES

    modeles = {famille.value: liste for famille, liste in MODELES.items()}
    return _TEMPLATE.format(
        target=target,
        features=features,
        budget=int(budget or BUDGET_SECONDES),
        seuil_desequilibre=SEUIL_DESEQUILIBRE,
        vif_avert=VIF_AVERTISSEMENT,
        vif_bloq=VIF_BLOQUANT,
        alpha=ALPHA,
        dw_min=DW_MIN,
        dw_max=DW_MAX,
        epv_min=EPV_MIN,
        ecart_surapp=ECART_SURAPPRENTISSAGE,
        r2_min=R2_MIN_UTILE,
        gain_rmse=GAIN_RMSE_MIN,
        mcc_min=MCC_MIN_UTILE,
        qualite_r2=QUALITE_R2,
        qualite_mcc=QUALITE_MCC,
        modeles=modeles,
    )
