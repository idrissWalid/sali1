"""timeseries_service.py — Moteur de prévision automatique, exécuté dans le sandbox.

Contrairement au pipeline rigoureux (dont le code est écrit par le LLM puis
autocorrigé), ce moteur exécute un script **déterministe** : il met en concurrence
plusieurs modèles statistiques (AutoARIMA, AutoETS, AutoTheta, SeasonalNaive) et
retient le meilleur sur un holdout out-of-sample.

Il tourne dans le container Docker isolé, donc sans réseau. C'est la raison pour
laquelle il s'appuie sur `statsforecast` — la brique statistique offline que
TimeCopilot utilise lui aussi — et non sur l'agent TimeCopilot, qui exige un accès
à l'API d'un LLM et le téléchargement de poids depuis HuggingFace. L'interprétation
en langage naturel reste faite côté hôte, où la clé API vit déjà.

Les seuils de décision (GATE 1 / GATE 2) reprennent ceux de
`methodologie_series_temporelles_agent.md` : Ljung-Box p > 0,05 aux retards s et 2s,
MAPE <= 20 % et couverture de l'IC 95 % >= 70 %.
"""

import io
import re

from app.services.sandbox_service import execute_code

# Seuils normatifs (cf. méthodologie, étapes F et G).
_LJUNG_BOX_ALPHA = 0.05
_MAPE_MAX_PCT = 20.0
_COVERAGE_MIN_PCT = 70.0

_DATE_NAME_RE = re.compile(
    r"date|mois|month|year|ann[ée]e|time|timestamp|jour|day|periode|période|semaine|week",
    re.I,
)


def detect_timeseries_columns(df) -> tuple[list[str], list[str]]:
    """Colonnes exploitables comme (axe temporel, valeur à prévoir).

    Source unique de vérité : le sélecteur du frontend et la détection
    automatique du chat doivent s'accorder sur ce qui compte comme une date.
    """
    import pandas as pd

    n_rows = len(df)
    dates: list[str] = []
    valeurs: list[str] = []
    for col in df.columns:
        if df[col].dropna().empty:
            continue
        is_datetime = pd.api.types.is_datetime64_any_dtype(df[col])
        parses_as_date = False
        if not is_datetime and _DATE_NAME_RE.search(str(col)):
            try:
                parsed = pd.to_datetime(df[col], errors="coerce")
                parses_as_date = parsed.notna().sum() >= max(3, 0.5 * n_rows)
            except Exception:
                parses_as_date = False
        if is_datetime or parses_as_date:
            dates.append(str(col))
        if pd.api.types.is_numeric_dtype(df[col]):
            valeurs.append(str(col))
    return dates, valeurs


def infer_series_columns(file_bytes: bytes, filename: str) -> tuple[str | None, str | None]:
    """Meilleur couple (date, valeur) pour une demande en langage naturel, où
    l'utilisateur n'a désigné aucune colonne. Renvoie (None, None) si la table ne
    permet pas de constituer une série."""
    import pandas as pd

    try:
        ext = (filename or "").rsplit(".", 1)[-1].lower()
        df = (pd.read_csv(io.BytesIO(file_bytes)) if ext == "csv"
              else pd.read_excel(io.BytesIO(file_bytes)))
    except Exception:
        return None, None

    dates, valeurs = detect_timeseries_columns(df)
    if not dates or not valeurs:
        return None, None
    # La valeur ne peut pas être l'axe temporel lui-même (une colonne d'années
    # est à la fois numérique et parsable en date).
    valeur = next((v for v in valeurs if v != dates[0]), None)
    return (dates[0], valeur) if valeur else (None, None)


def build_autoforecast_code(
    date_col: str,
    value_col: str,
    horizon: int | None = None,
) -> str:
    """Script de prévision automatique à exécuter dans le sandbox.

    Produit `metrics.json` au format normatif `TimeSeriesOutput` et une figure
    (historique + prévision + IC 95 %).
    """
    return _AUTOFORECAST_TEMPLATE.format(
        date_col=repr(date_col),
        value_col=repr(value_col),
        horizon=repr(horizon),
        lb_alpha=_LJUNG_BOX_ALPHA,
        mape_max=_MAPE_MAX_PCT,
        cov_min=_COVERAGE_MIN_PCT,
    )


def run_autoforecast(
    file_bytes: bytes,
    filename: str,
    date_col: str,
    value_col: str,
    horizon: int | None = None,
) -> dict:
    """Exécute le moteur automatique dans le sandbox.

    Returns:
        dict: { metrics (dict|None), images (list[str]), output (str), error (dict|None) }
    """
    code = build_autoforecast_code(date_col, value_col, horizon)
    result = execute_code(code, dataframe_bytes=file_bytes, filename=filename)

    # Le script peut se terminer sans exception mais sans metrics.json (série
    # inexploitable) : on le signale comme une erreur plutôt que de laisser
    # l'appelant enregistrer un modèle vide.
    if not result.get("error") and not result.get("metrics"):
        output = (result.get("output") or "").strip()
        result["error"] = {
            "technical": output or "Aucun metrics.json produit par le moteur automatique.",
            "simple": "Le moteur de prévision automatique n'a produit aucun résultat exploitable.",
        }
    return result


# Le script est volontairement défensif : chaque diagnostic est isolé dans un
# try/except et se dégrade en "NON_CALCULE" plutôt que de faire échouer la
# prévision entière.
_AUTOFORECAST_TEMPLATE = '''
import json, math, warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

DATE_COL = {date_col}
VALUE_COL = {value_col}
HORIZON_REQ = {horizon}
LB_ALPHA = {lb_alpha}
MAPE_MAX = {mape_max}
COV_MIN = {cov_min}

avertissements = []

# --- Etape A : inventaire et mise sur grille reguliere ----------------------
s = df[[DATE_COL, VALUE_COL]].copy()
s[DATE_COL] = pd.to_datetime(s[DATE_COL], errors="coerce")
s[VALUE_COL] = pd.to_numeric(s[VALUE_COL], errors="coerce")
s = s.dropna(subset=[DATE_COL]).sort_values(DATE_COL)
if s.empty:
    raise ValueError("Aucune date exploitable dans la colonne " + str(DATE_COL))

serie = s.set_index(DATE_COL)[VALUE_COL]
if serie.index.has_duplicates:
    n_dup = int(serie.index.duplicated().sum())
    serie = serie.groupby(level=0).mean()
    avertissements.append(str(n_dup) + " dates en doublon agregees par moyenne.")

freq = pd.infer_freq(serie.index)
if freq is None:
    # Pas de frequence inferable (trous, dates irregulieres) : on la deduit de
    # l'ecart median entre observations.
    days = serie.index.to_series().diff().dt.total_seconds().median() / 86400.0
    if days <= 0.0417:   freq = "h"
    elif days <= 1.5:    freq = "D"
    elif days <= 8.0:    freq = "W"
    elif days <= 45.0:   freq = "MS"
    elif days <= 135.0:  freq = "QS"
    else:                freq = "YS"
    avertissements.append("Frequence non inferable, estimee a '" + freq + "' d'apres l'ecart median.")

serie = serie.asfreq(freq)   # trous eventuels -> NaN, conserves tels quels

_SEASON = {{"h": 24, "D": 7, "W": 52, "M": 12, "MS": 12, "ME": 12,
           "Q": 4, "QS": 4, "QE": 4, "Y": 1, "YS": 1, "YE": 1}}
base_freq = freq.split("-")[0]
season = _SEASON.get(base_freq, 1)

n_obs = int(len(serie))
n_missing = int(serie.isna().sum())
if n_missing:
    avertissements.append(str(n_missing) + " valeur(s) manquante(s) interpolee(s) pour l'estimation.")

# Serie d'estimation : interpolee. L'historique restitue reste la serie brute,
# trous compris (null en JSON) — ne jamais presenter des valeurs inventees comme
# des observations.
y = serie.interpolate(method="time").ffill().bfill()
if y.isna().all():
    raise ValueError("La colonne " + str(VALUE_COL) + " ne contient aucune valeur numerique.")

if n_obs < 2 * season or season < 2:
    if season >= 2:
        avertissements.append("Serie trop courte pour la saisonnalite " + str(season) + " : modeles non saisonniers.")
    season = 1

# --- Etape C : decision de transformation (jamais de log par defaut) --------
# On regresse l'ecart-type de chaque fenetre saisonniere glissante sur sa moyenne.
# Une pente significativement positive signale une saisonnalite multiplicative.
log_applique = False
log_justification = "Test non applicable (serie trop courte) : echelle d'origine conservee."
if season > 1 and n_obs >= 3 * season and (y > 0).all():
    try:
        roll_m = y.rolling(season).mean().dropna()
        roll_s = y.rolling(season).std().dropna()
        import statsmodels.api as _sm
        _fit = _sm.OLS(roll_s.values, _sm.add_constant(roll_m.values)).fit()
        pente, p_pente = float(_fit.params[1]), float(_fit.pvalues[1])
        if pente > 0 and p_pente < 0.05:
            log_applique = True
            log_justification = (
                "Amplitude saisonniere croissante avec le niveau (pente "
                + str(round(pente, 4)) + ", p=" + format(p_pente, ".2e")
                + " < 0.05) : log appliquee."
            )
        else:
            log_justification = (
                "Pente ecart-type/moyenne non significativement positive (pente "
                + str(round(pente, 4)) + ", p=" + format(p_pente, ".3f")
                + ") : echelle d'origine conservee."
            )
    except Exception as exc:
        log_justification = "Test de transformation impossible (" + str(exc) + ") : echelle d'origine conservee."
elif not (y > 0).all():
    log_justification = "Valeurs nulles ou negatives presentes : log impossible, echelle d'origine conservee."

y_model = np.log(y) if log_applique else y

# --- Panel de modeles concurrents -------------------------------------------
from statsforecast import StatsForecast
from statsforecast.models import AutoARIMA, AutoETS, AutoTheta, SeasonalNaive

models = [AutoARIMA(season_length=season), AutoETS(season_length=season),
          AutoTheta(season_length=season)]
if season > 1:
    models.append(SeasonalNaive(season_length=season))

sdf = pd.DataFrame({{"unique_id": "serie", "ds": y_model.index, "y": y_model.values.astype(float)}})

# --- Etape G : holdout out-of-sample (12-24 obs, ou 20% si plus petit) -------
h_test = int(min(max(12, season), max(2, n_obs // 5), 24))
h_test = max(2, min(h_test, n_obs - max(3, season + 1)))
train, test = sdf.iloc[:-h_test], sdf.iloc[-h_test:]

sf = StatsForecast(models=models, freq=freq, n_jobs=1)
cv = sf.forecast(df=train, h=h_test, level=[95])

def _inv(a):
    """Retour a l'echelle d'origine. Metriques et previsions doivent etre lues
    dans l'unite de la serie, jamais en log."""
    return np.exp(a) if log_applique else a


actual = _inv(test["y"].to_numpy(dtype=float))
scores = []
for m in models:
    name = repr(m)
    if name not in cv.columns:
        continue
    pred = _inv(cv[name].to_numpy(dtype=float))
    lo, hi = cv.get(name + "-lo-95"), cv.get(name + "-hi-95")
    err = actual - pred
    rmse = float(np.sqrt(np.mean(err ** 2)))
    nz = actual != 0
    mape = float(np.mean(np.abs(err[nz] / actual[nz])) * 100) if nz.any() else float("inf")
    if lo is not None and hi is not None:
        inside = ((actual >= _inv(lo.to_numpy(dtype=float)))
                  & (actual <= _inv(hi.to_numpy(dtype=float))))
        cov = float(np.mean(inside) * 100)
    else:
        cov = None
    if math.isfinite(rmse) and math.isfinite(mape):
        scores.append({{"nom": name, "mape": mape, "rmse": rmse, "couverture": cov}})

if not scores:
    raise ValueError("Aucun modele n'a produit de prevision exploitable sur le holdout.")

# Classement par MAPE ; a MAPE egale, le RMSE tranche.
scores.sort(key=lambda d: (d["mape"], d["rmse"]))
best = scores[0]
best_model = [m for m in models if repr(m) == best["nom"]][0]
if len(scores) > 1:
    avertissements.append(
        "Modeles compares (MAPE holdout) : "
        + ", ".join(d["nom"] + " " + str(round(d["mape"], 2)) + "%" for d in scores) + "."
    )

# --- Re-estimation sur la serie complete avant la prevision livree -----------
horizon = int(HORIZON_REQ) if HORIZON_REQ else max(season, 12)


def _diagnostics_residus(sf_fitted, col):
    """GATE 1 : Ljung-Box aux retards s et 2s, + Jarque-Bera et ARCH."""
    out = {{"ljung_box_p_lag_s": None, "ljung_box_p_lag_2s": None,
           "jarque_bera_p": None, "arch_p": None, "statut": "NON_CALCULE"}}
    try:
        ins = sf_fitted.forecast_fitted_values()
        resid = pd.Series((ins["y"] - ins[col]).to_numpy(dtype=float)).dropna()
        # Ecarter la periode d'initialisation diffuse : ses residus de demarrage
        # fausseraient Ljung-Box et Jarque-Bera (piege n.1 de la methodologie).
        resid = resid.iloc[(season if season > 1 else 1):]
        from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
        from scipy import stats as _st
        lags = sorted(l for l in ([season, 2 * season] if season > 1 else [10, 20])
                      if 0 < l < len(resid) // 2)
        if lags:
            vals = acorr_ljungbox(resid, lags=lags, return_df=True)["lb_pvalue"].tolist()
            out["ljung_box_p_lag_s"] = float(vals[0])
            if len(vals) > 1:
                out["ljung_box_p_lag_2s"] = float(vals[1])
        try:
            out["jarque_bera_p"] = float(_st.jarque_bera(resid)[1])
        except Exception:
            pass
        try:
            out["arch_p"] = float(het_arch(resid, nlags=min(12, max(1, len(resid) // 5)))[1])
        except Exception:
            pass
        checked = [p for p in (out["ljung_box_p_lag_s"], out["ljung_box_p_lag_2s"]) if p is not None]
        if checked:
            # Jarque-Bera est souhaitable mais non bloquant (methodologie §7).
            out["statut"] = "PASS" if all(p > LB_ALPHA for p in checked) else "FAIL"
    except Exception as exc:
        out["_erreur"] = str(exc)
    return out


def _parametres_modele(model_obj):
    """(p,d,q), (P,D,Q,s), AIC/BIC et coefficients — pour AutoARIMA seulement.

    `forecast()` ne conserve pas les modeles ajustes (`fitted_` reste vide) : il
    faut un `fit()` explicite pour acceder aux parametres estimes.
    """
    ordre = saison = aic = bic = None
    coefs = []
    try:
        sf_p = StatsForecast(models=[model_obj], freq=freq, n_jobs=1)
        sf_p.fit(sdf)
        fitted = sf_p.fitted_[0][0].model_
        if "arma" in fitted:
            # statsforecast expose arma = (p, q, P, Q, s, d, D)
            p, q, P, Q, m_, d, D = [int(v) for v in fitted["arma"]]
            ordre = [p, d, q]
            if season > 1 and (P or D or Q):
                saison = [P, D, Q, m_]
        aic = fitted.get("aic")
        bic = fitted.get("bic")
        aic = float(aic) if aic is not None else None
        bic = float(bic) if bic is not None else None
        # Significativite des coefficients : var_coef donne les variances, d'ou
        # un test de Wald (methodologie §7, dernier critere du GATE 1).
        noms = list(fitted.get("coef", {{}}).keys())
        vals = list(fitted.get("coef", {{}}).values())
        var = fitted.get("var_coef")
        for i, (nm, vl) in enumerate(zip(noms, vals)):
            pv = None
            try:
                se = float(np.sqrt(var[i][i]))
                if se > 0:
                    from scipy import stats as _st2
                    pv = float(2 * (1 - _st2.norm.cdf(abs(float(vl) / se))))
            except Exception:
                pv = None
            if pv is not None:
                coefs.append({{"nom": str(nm), "valeur": float(vl), "p_value": pv}})
    except Exception:
        pass
    return ordre, saison, aic, bic, coefs


# Le classement out-of-sample ordonne les candidats ; il ne les valide pas. On
# descend le classement jusqu'au premier modele qui passe AUSSI le GATE 1
# (methodologie §6-7 : « l'AIC minimal n'implique pas la validite du modele »).
retenu = None
premier = None
for cand in scores:
    obj = [m for m in models if repr(m) == cand["nom"]][0]
    sf_c = StatsForecast(models=[obj], freq=freq, n_jobs=1)
    try:
        fut_c = sf_c.forecast(df=sdf, h=horizon, level=[95], fitted=True)
    except Exception as exc:
        avertissements.append("Re-estimation impossible pour " + cand["nom"] + " : " + str(exc))
        continue

    g1 = _diagnostics_residus(sf_c, cand["nom"])
    cov_c = cand["couverture"]
    g2_ok = cand["mape"] <= MAPE_MAX and (cov_c is None or cov_c >= COV_MIN)
    g2 = {{"horizon_test": h_test, "mape_pct": cand["mape"], "rmse": cand["rmse"],
          "couverture_ic95_pct": cov_c, "statut": "PASS" if g2_ok else "FAIL"}}

    courant = {{"cand": cand, "obj": obj, "fut": fut_c, "g1": g1, "g2": g2}}
    if premier is None:
        premier = courant
    if g1["statut"] == "PASS" and g2_ok:
        retenu = courant
        break
    avertissements.append(
        cand["nom"] + " ecarte (GATE 1 " + g1["statut"] + ", GATE 2 " + g2["statut"] + ")."
    )

if retenu is None:
    # Aucun candidat ne passe les deux gates : on livre le mieux classe, mais le
    # statut final dira explicitement que la prevision n'est pas validee.
    retenu = premier
    if retenu is None:
        raise ValueError("Aucun modele n'a pu etre re-estime sur la serie complete.")

best = retenu["cand"]
col = best["nom"]
fut = retenu["fut"]
gate1_report = retenu["g1"]
gate2_report = retenu["g2"]
gate1 = gate1_report["statut"]
gate2 = gate2_report["statut"]
cov_best = best["couverture"]

if gate1_report.get("_erreur"):
    avertissements.append("Diagnostics des residus indisponibles : " + gate1_report.pop("_erreur"))
if gate1 == "FAIL":
    avertissements.append("Autocorrelation residuelle significative (Ljung-Box p <= " + str(LB_ALPHA) + ").")
if best["mape"] > MAPE_MAX:
    avertissements.append("MAPE holdout " + str(round(best["mape"], 2)) + "% > " + str(MAPE_MAX) + "%.")
if cov_best is not None and cov_best < COV_MIN:
    avertissements.append("Couverture IC95 " + str(round(cov_best, 1)) + "% < " + str(COV_MIN) + "% : intervalles trop etroits.")

if gate1 == "PASS" and gate2 == "PASS":
    statut_final = "MODELE_VALIDE"
elif gate2 == "FAIL":
    statut_final = "MODELE_REJETE"
else:
    statut_final = "INCERTITUDE_ELEVEE"

ordre, ordre_saisonnier, aic, bic, coefficients = _parametres_modele(retenu["obj"])
non_significatifs = [c["nom"] for c in coefficients if c["p_value"] > 0.05]
if non_significatifs:
    avertissements.append(
        "Coefficient(s) non significatif(s) au seuil 5% : " + ", ".join(non_significatifs) + "."
    )
if ordre and ordre_saisonnier:
    type_modele = "SARIMA"
elif ordre:
    type_modele = "ARIMA"
else:
    type_modele = col

# --- Graphique : historique + prevision + IC 95% -----------------------------
fd = pd.to_datetime(fut["ds"])
pred_finale = _inv(fut[col].to_numpy(dtype=float))
has_ic = (col + "-lo-95") in fut.columns
ic_bas = _inv(fut[col + "-lo-95"].to_numpy(dtype=float)) if has_ic else None
ic_haut = _inv(fut[col + "-hi-95"].to_numpy(dtype=float)) if has_ic else None
if log_applique:
    avertissements.append(
        "Prevision obtenue par exponentielle du modele en log : elle estime la "
        "mediane conditionnelle, legerement inferieure a la moyenne."
    )

fig, ax = plt.subplots(figsize=(11, 5))
ax.plot(serie.index, serie.values, color="#4da3ff", lw=1.6, label="Historique")
ax.plot(fd, pred_finale, color="#ff9f43", lw=2, label="Prevision (" + type_modele + ")")
if has_ic:
    ax.fill_between(fd, ic_bas, ic_haut, color="#ff9f43", alpha=0.2, label="IC 95%")
ax.set_title(str(VALUE_COL) + " — prevision sur " + str(horizon) + " periodes")
ax.set_xlabel(str(DATE_COL)); ax.set_ylabel(str(VALUE_COL))
ax.legend(loc="best"); ax.grid(alpha=0.2)
fig.autofmt_xdate()

# --- Contrat de sortie -------------------------------------------------------
def _num(v):
    """NaN/Inf -> None : le JSON standard ne les admet pas."""
    if v is None:
        return None
    f = float(v)
    return f if math.isfinite(f) else None

historique = [
    {{"date": d.strftime("%Y-%m-%d"), "valeur": _num(v)}}
    for d, v in zip(serie.index, serie.values)
]
prevision = []
for i in range(len(fut)):
    vp = _num(pred_finale[i])
    if vp is None:
        continue
    prevision.append({{
        "date": fd.iloc[i].strftime("%Y-%m-%d"),
        "valeur_prevue": vp,
        "ic_bas": _num(ic_bas[i]) if has_ic else None,
        "ic_haut": _num(ic_haut[i]) if has_ic else None,
    }})

report = {{
    "serie": {{"n_observations": n_obs, "frequence": freq, "saisonnalite_detectee": season}},
    "transformation": {{"log_applique": log_applique, "justification": log_justification}},
    "stationnarite": {{"d": ordre[1] if ordre else None,
                      "D": ordre_saisonnier[1] if ordre_saisonnier else None,
                      "adf_p_value_finale": None, "kpss_p_value_finale": None}},
    "modele_retenu": {{"type": type_modele, "ordre": ordre, "ordre_saisonnier": ordre_saisonnier,
                      "aic": _num(aic), "bic": _num(bic), "coefficients": coefficients}},
    "gate_1_diagnostics_residus": {{k: (_num(v) if k != "statut" else v)
                                   for k, v in gate1_report.items()}},
    "gate_2_validation_out_of_sample": {{k: (_num(v) if k not in ("statut", "horizon_test") else v)
                                        for k, v in gate2_report.items()}},
    "statut_final": statut_final,
    "avertissements": avertissements,
    "historique": historique,
    "prevision": prevision,
}}

with open("metrics.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, allow_nan=False)

print("Modele retenu :", type_modele, "| MAPE holdout", round(best["mape"], 2), "%")
print("GATE 1:", gate1, "| GATE 2:", gate2, "| statut final:", statut_final)
'''
