# Méthodologie normative — Modélisation de séries temporelles (SARIMA)
### Guide de raisonnement pour agent IA (ML Sandbox — NCDI)

---

## 0. Objectif de ce document

Ce document normalise le raisonnement qu'un agent doit exécuter **automatiquement**, sans supervision humaine, lorsqu'une requête utilisateur implique une prévision sur série temporelle. Il ne s'agit pas d'un exemple à imiter approximativement : c'est un **contrat procédural**. Chaque étape produit une sortie vérifiable, et chaque sortie déclenche une règle de décision explicite (if/else), pas un jugement libre du LLM.

**Principe directeur (à ne jamais violer) :**
> Un code qui s'exécute sans erreur n'est PAS un modèle validé. La validation repose sur deux piliers indépendants :
> 1. **Validité statistique** — les hypothèses du modèle sont vérifiées (résidus = bruit blanc, pas d'autocorrélation résiduelle).
> 2. **Performance prédictive** — le modèle généralise sur des données non vues (métriques out-of-sample sous seuil).
>
> Un agent qui livre une prévision sans avoir vérifié 1 ET 2 est en échec de tâche, même si le script tourne parfaitement.

---

## 1. Vue d'ensemble du pipeline obligatoire

```
Entrée: série temporelle univariée (colonne date + colonne valeur)
   │
   ▼
[Étape A] Prétraitement & inventaire de la série
   │
   ▼
[Étape B] Tests de stationnarité (ADF + KPSS croisés)
   │
   ▼
[Étape C] Décision de transformation (log ? Box-Cox ?)
   │
   ▼
[Étape D] Détermination de (d, D, s) par différenciation itérative
   │
   ▼
[Étape E] Sélection de modèle candidat (grid search AIC/BIC)
   │
   ▼
[Étape F] Diagnostic des résidus (GATE 1 — bloquant)
   │         ├── ÉCHEC → retour à l'étape E avec modèle suivant du classement
   │         └── SUCCÈS ↓
   ▼
[Étape G] Validation out-of-sample (GATE 2 — bloquant)
   │         ├── ÉCHEC → retour à l'étape E ou signalement d'incertitude élevée
   │         └── SUCCÈS ↓
   ▼
[Étape H] Prévision finale + intervalle de confiance + rapport metrics.json
```

Aucune étape ne peut être sautée. Aucune sortie finale ne peut être présentée à l'utilisateur si GATE 1 ou GATE 2 est en échec — dans ce cas, l'agent doit soit boucler sur un autre modèle, soit répondre explicitement que la série ne permet pas une prévision fiable.

---

## 2. Étape A — Prétraitement & inventaire

L'agent DOIT produire, avant toute modélisation :

- Fréquence de la série (mensuelle, journalière, etc.) et nombre d'observations `n`.
- Détection de valeurs manquantes → imputation ou signalement.
- Détection de la longueur de saisonnalité `s` candidate (12 pour mensuel avec cycle annuel, 7 pour journalier avec cycle hebdo, etc.) via une heuristique basée sur la fréquence déclarée — PAS par supposition du LLM.

**Règle de refus :** si `n < 3 * s` (moins de 3 cycles saisonniers complets), l'agent doit refuser un modèle saisonnier et proposer un modèle non-saisonnier ou signaler l'insuffisance de données.

---

## 3. Étape B — Tests de stationnarité

Appliquer **deux tests complémentaires**, jamais un seul (ils ont des hypothèses nulles opposées, ce qui limite les faux positifs) :

| Test | H0 | Rejet si |
|---|---|---|
| ADF (Augmented Dickey-Fuller) | Série non-stationnaire | p-value < 0,05 |
| KPSS | Série stationnaire | p-value < 0,05 |

**Table de décision croisée (obligatoire, pas d'interprétation libre) :**

| ADF rejette H0 ? | KPSS rejette H0 ? | Conclusion |
|---|---|---|
| Oui | Non | Stationnaire → conserver |
| Non | Oui | Non-stationnaire → différencier |
| Oui | Oui | Résultats contradictoires → différencier par précaution et re-tester |
| Non | Non | Données insuffisantes / test peu concluant → différencier par précaution et re-tester |

---

## 4. Étape C — Décision de transformation

Avant toute différenciation, vérifier si l'amplitude de la saisonnalité **croît avec le niveau de la série** (saisonnalité multiplicative) :

- Calcul automatique : régresser l'écart-type de chaque fenêtre annuelle glissante sur la moyenne de cette même fenêtre.
- Si la pente est significativement positive (p < 0,05) → appliquer **log(y)**.
- Sinon → conserver l'échelle originale.

Ne jamais appliquer une transformation log par défaut ni par habitude : la décision doit être justifiée par ce test, journalisée dans le rapport.

---

## 5. Étape D — Différenciation itérative (détermination de d et D)

Procédure algorithmique stricte :

1. Partir de `d=0, D=0`.
2. Tester stationnarité (étape B) sur la série (transformée si applicable).
3. Si non-stationnaire → appliquer une différenciation saisonnière (`D += 1`, diff à `s`) si un pattern saisonnier est visible sur l'ACF (pics périodiques à des multiples de `s`), sinon différenciation simple (`d += 1`).
4. Répéter jusqu'à stationnarité confirmée.
5. **Garde-fou :** stopper et signaler une anomalie si `d + D > 2` (sur-différenciation, risque de bruit introduit).

---

## 6. Étape E — Sélection de modèle (grid search)

- Grille bornée : `p, q, P, Q ∈ {0, 1, 2}` (jamais illimité — coût combinatoire et risque de sur-ajustement).
- Critère de tri primaire : AIC. Conserver les **5 meilleurs modèles**, pas seulement le premier.
- **Règle non-négociable :** l'AIC/BIC sert à ORDONNER les candidats, jamais à VALIDER un modèle seul. Le modèle avec le meilleur AIC peut échouer au GATE 1 (voir cas réel ci-dessous) — dans ce cas l'agent doit essayer le candidat suivant du classement, pas abandonner.

> **Exemple vécu (AirPassengers) à inclure dans le raisonnement de l'agent comme cas de référence :**
> Le modèle de meilleur AIC (-445,4) a échoué au test de Ljung-Box (p=0,00008 à 12 retards — autocorrélation résiduelle significative). Le modèle classé 6ᵉ par AIC (-435,4) a passé tous les diagnostics (Ljung-Box p=0,75 et 0,49 ; Jarque-Bera p=0,37). C'est ce dernier qui a été retenu. **L'AIC minimal n'implique pas la validité du modèle.**

---

## 7. Étape F — GATE 1 : Diagnostic des résidus (bloquant)

Pour chaque candidat testé, calculer sur les résidus **en excluant la période d'initialisation diffuse** (les `d + D×s` premières observations, dont la variance est artificiellement gonflée par l'initialisation du filtre de Kalman — piège fréquent qui fausse tous les tests si ignoré) :

| Test | Objectif | Critère de passage |
|---|---|---|
| Ljung-Box (lags = saisonnalité et 2×saisonnalité) | Absence d'autocorrélation résiduelle | p-value > 0,05 aux deux horizons |
| Jarque-Bera | Normalité des résidus | p-value > 0,05 (souhaitable, non strictement bloquant si les autres tests passent) |
| Test ARCH (hétéroscédasticité résiduelle) | Variance résiduelle stable | p-value > 0,05 |
| Significativité des coefficients | Pas de paramètres inutiles | p-value < 0,05 pour chaque coefficient estimé |

**Règle de décision :**
```
SI Ljung-Box échoue (p < 0.05 à un des deux horizons):
    → modèle REJETÉ, passer au candidat suivant du classement AIC
SINON SI un coefficient a p-value > 0.05:
    → modèle simplifié (retirer le paramètre non-significatif) et ré-estimé
SINON:
    → modèle ADMIS au GATE 1, passer à l'étape G
```

---

## 8. Étape G — GATE 2 : Validation out-of-sample (bloquant, performance)

C'est l'étape que les agents omettent le plus souvent — **ne jamais valider un modèle uniquement sur données d'entraînement.**

Procédure :

1. Réserver les **12 à 24 dernières observations** (ou 20% de la série, le plus petit des deux) comme ensemble de test, jamais vues pendant l'estimation.
2. Ré-estimer le modèle retenu (étape F) uniquement sur l'ensemble d'entraînement.
3. Produire une prévision sur l'horizon de test, avec intervalle de confiance à 95%.
4. Calculer les métriques suivantes sur l'ensemble de test :

| Métrique | Formule | Seuil d'acceptation (à adapter au domaine, mais toujours explicite) |
|---|---|---|
| MAPE (%) | moyenne(\|réel−prévu\|/réel) × 100 | < 10% : bon ; 10–20% : acceptable ; > 20% : rejeté par défaut |
| RMSE | racine(moyenne((réel−prévu)²)) | comparé à l'écart-type de la série de test |
| Taux de couverture de l'IC 95% | % de points réels tombant dans l'IC | doit être proche de 95% (tolérance 80–100%) ; un taux < 70% signale des IC trop étroits (sous-estimation de l'incertitude) |

**Règle de décision :**
```
SI MAPE > 20% OU couverture IC < 70%:
    → modèle REJETÉ pour insuffisance de performance
    → retour à l'étape E (candidat suivant) OU signalement explicite d'incertitude élevée à l'utilisateur
SINON:
    → modèle ADMIS au GATE 2 → autorisé à produire la prévision finale
```

5. Une fois validé sur le holdout, ré-estimer le modèle final sur **l'intégralité de la série** (train+test) avant de produire la prévision future réellement demandée par l'utilisateur — ne jamais livrer une prévision produite par un modèle entraîné sur des données tronquées.

---

## 9. Étape H — Contrat de sortie (`metrics.json`)

L'agent doit produire un objet structuré, jamais du texte libre, en sortie du pipeline. Schéma minimal (compatible Pydantic) :

```json
{
  "serie": {
    "n_observations": 144,
    "frequence": "MS",
    "saisonnalite_detectee": 12
  },
  "transformation": {
    "log_applique": true,
    "justification": "pente significative amplitude/niveau (p=0.00X)"
  },
  "stationnarite": {
    "d": 1,
    "D": 1,
    "adf_p_value_finale": 0.0002,
    "kpss_p_value_finale": 0.14
  },
  "modele_retenu": {
    "ordre": [0, 1, 1],
    "ordre_saisonnier": [0, 1, 1, 12],
    "aic": -435.44,
    "bic": -427.16,
    "coefficients": [
      {"nom": "ma.L1", "valeur": -0.4326, "p_value": 0.0000},
      {"nom": "ma.S.L12", "valeur": -0.5476, "p_value": 0.0000}
    ]
  },
  "gate_1_diagnostics_residus": {
    "ljung_box_p_lag_s": 0.754,
    "ljung_box_p_lag_2s": 0.493,
    "jarque_bera_p": 0.369,
    "statut": "PASS"
  },
  "gate_2_validation_out_of_sample": {
    "horizon_test": 12,
    "mape_pct": 2.88,
    "rmse": 18.49,
    "couverture_ic95_pct": 91.7,
    "statut": "PASS"
  },
  "statut_final": "MODELE_VALIDE",
  "avertissements": []
}
```

**Règle stricte pour l'agent :** si `gate_1_diagnostics_residus.statut` ou `gate_2_validation_out_of_sample.statut` vaut `"FAIL"`, alors `statut_final` DOIT être `"MODELE_REJETE"` ou `"INCERTITUDE_ELEVEE"` — jamais `"MODELE_VALIDE"`. Le champ `statut_final` conditionne si l'agent est autorisé à afficher une prévision à l'utilisateur.

---

## 10. Squelette de prompt / raisonnement pour le LLM exécutant dans le sandbox

```
Tu es un agent d'analyse de séries temporelles opérant dans un sandbox Docker.
Tu DOIS suivre les étapes A à H dans l'ordre, sans en sauter aucune.
Après CHAQUE étape, tu écris le résultat numérique obtenu (pas une estimation
verbale) avant de passer à l'étape suivante.
Tu ne peux déclarer un modèle "validé" que si gate_1 ET gate_2 sont PASS.
Si un gate échoue, tu dois soit essayer le candidat suivant du classement AIC
(retour étape E), soit, après épuisement des 5 candidats, répondre à
l'utilisateur que la série ne permet pas de prévision fiable avec le niveau
de confiance demandé — tu ne dois jamais présenter un résultat non validé
comme définitif.
Ta sortie finale est TOUJOURS un objet metrics.json conforme au schéma de
la section 9, accompagné du graphique de prévision avec intervalle de
confiance.
```

---

## 11. Erreurs fréquentes à interdire explicitement à l'agent

1. **Ne pas exclure la période d'initialisation diffuse** avant de calculer les tests sur les résidus → fausse totalement Ljung-Box et Jarque-Bera (résidus de démarrage artificiellement énormes).
2. **Choisir le modèle au seul critère AIC** sans passer les résidus au test de Ljung-Box.
3. **Valider uniquement en échantillon (in-sample)** — un R² ou une erreur calculée sur les données d'entraînement ne prouve rien sur la capacité de généralisation.
4. **Considérer qu'un script sans exception Python constitue une validation** — c'est une condition nécessaire mais non suffisante.
5. **Appliquer une transformation log par réflexe** sans test préalable de l'hétéroscédasticité multiplicative.
6. **Ignorer le taux de couverture de l'intervalle de confiance** — un IC peut être numériquement valide mais statistiquement inutile s'il est mal calibré (couverture réelle très différente de 95%).
