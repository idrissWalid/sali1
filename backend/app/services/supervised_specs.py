"""supervised_specs.py — Règles du tournoi supervisé.

Le moteur teste plusieurs modèles en concurrence et livre le meilleur. Un modèle
n'est « bon » que si TROIS conditions sont réunies, pas seulement la première :

  1. il s'exécute sans erreur ;
  2. ses hypothèses statistiques bloquantes sont respectées ;
  3. ses performances battent une baseline triviale et ne trahissent pas de
     surapprentissage.

Ce fichier centralise les seuils et le statut de chaque hypothèse. Il est importé
côté hôte (pour l'interprétation et les tests) et son contenu est injecté dans le
script exécuté en sandbox : une seule source de vérité pour les deux.
"""

from enum import Enum


class Famille(str, Enum):
    """Déterminée automatiquement d'après la cible — l'utilisateur ne choisit pas."""

    REGRESSION = "regression"
    CLASSIFICATION = "classification"
    CLASSIFICATION_DESEQUILIBREE = "classification_desequilibree"


# En dessous de cette part, la classe minoritaire bascule le problème sur la
# famille déséquilibrée : seuil optimisé, métriques PR plutôt qu'accuracy.
SEUIL_DESEQUILIBRE = 0.20

# Budget global du tournoi. On s'arrête avant si un modèle satisfait TOUTES les
# normes : inutile de consommer le budget quand le résultat est déjà bon.
BUDGET_SECONDES = 600

# ── Seuils des hypothèses ────────────────────────────────────────────────────
VIF_AVERTISSEMENT = 5.0
VIF_BLOQUANT = 10.0
ALPHA = 0.05
# Durbin-Watson : ~2 = pas d'autocorrélation. On ne bloque que sur un écart franc,
# une légère dérive n'invalidant pas les intervalles de confiance.
DW_MIN, DW_MAX = 1.0, 3.0
# Événements par variable : en dessous, les coefficients logistiques sont
# instables et leurs IC ininterprétables.
EPV_MIN = 10
# Écart relatif train/test au-delà duquel on déclare le surapprentissage.
ECART_SURAPPRENTISSAGE = 0.20

# ── Seuils d'utilité ─────────────────────────────────────────────────────────
# « Battre la baseline » pris au pied de la lettre (R² > 0) laisse passer des
# modèles inutilisables : un R² test de 0,037 améliore le RMSE de 1,9 % sur une
# simple moyenne, ce qui relève du bruit. On exige donc une marge signifiante,
# sans quoi le statut « MODELE_VALIDE » n'aurait aucune valeur informative.
R2_MIN_UTILE = 0.05          # en deçà, la régression n'explique rien d'exploitable
GAIN_RMSE_MIN = 0.05         # amélioration relative minimale du RMSE sur la moyenne
MCC_MIN_UTILE = 0.10         # MCC ~0 = hasard ; en deçà, l'association est négligeable

# Ces seuils sont des PLANCHERS DE BRUIT, pas des standards de qualité : un R² de
# 0,06 les franchit tout en restant un mauvais modèle. Un « validé » binaire
# masquerait cette nuance, et aucun seuil unique ne vaut pour tous les domaines
# (un R² de 0,3 est mediocre en physique, remarquable en sciences du
# comportement). On qualifie donc explicitement le niveau atteint, à charge pour
# l'utilisateur de juger s'il est suffisant pour SON usage.
QUALITE_R2 = [
    (0.75, "excellente"),
    (0.50, "bonne"),
    (0.25, "moderee"),
    (R2_MIN_UTILE, "faible"),
]
QUALITE_MCC = [
    (0.70, "excellente"),
    (0.50, "bonne"),
    (0.30, "moderee"),
    (MCC_MIN_UTILE, "faible"),
]


def qualifier(valeur: float | None, echelle: list[tuple[float, str]]) -> str:
    """Niveau de qualité atteint par une métrique, ou 'insuffisante'."""
    if valeur is None:
        return "inconnue"
    for seuil, libelle in echelle:
        if valeur >= seuil:
            return libelle
    return "insuffisante"

# ── Statut de chaque hypothèse ───────────────────────────────────────────────
# "bloquante"  : invalide le modèle, déclenche la remédiation
# "remediee"   : corrigée automatiquement (ex. erreurs-types robustes)
# "informative": signalée à l'utilisateur, jamais bloquante
#
# La normalité des résidus est délibérément informative : sur données réelles
# Shapiro-Wilk la rejette presque systématiquement dès n > 500, alors que le
# modèle reste parfaitement exploitable. La rendre bloquante condamnerait le
# tournoi à épuiser son budget pour finir en échec.
STATUT_HYPOTHESES = {
    "normalite_residus": "informative",
    "points_influents": "informative",
    "homoscedasticite": "remediee",       # → erreurs-types HC3
    "multicolinearite": "bloquante",      # au-delà de VIF_BLOQUANT
    "linearite": "bloquante",             # RESET de Ramsey
    "independance_residus": "bloquante",  # Durbin-Watson hors [DW_MIN, DW_MAX]
    "separation_complete": "bloquante",
    "epv_suffisant": "bloquante",
}

# ── Modèles engagés, dans l'ordre de passage ─────────────────────────────────
# Ordre = du plus rapide et interprétable au plus lourd. Si le premier satisfait
# toutes les normes, on livre sans exécuter les suivants.
MODELES = {
    Famille.REGRESSION: [
        ("ols", "Régression linéaire (OLS)"),
        ("elasticnet", "ElasticNet (α et l1_ratio par validation croisée)"),
        ("gradient_boosting", "Gradient Boosting"),
    ],
    Famille.CLASSIFICATION: [
        ("logistique", "Régression logistique"),
        ("random_forest", "Random Forest"),
        ("gradient_boosting", "Gradient Boosting"),
    ],
    Famille.CLASSIFICATION_DESEQUILIBREE: [
        ("logistique_ponderee", "Régression logistique pondérée"),
        ("balanced_random_forest", "Balanced Random Forest"),
        ("gradient_boosting_pondere", "Gradient Boosting pondéré"),
    ],
}

# ── Métrique de sélection ────────────────────────────────────────────────────
# Sur données déséquilibrées, l'accuracy est calculée mais JAMAIS utilisée pour
# choisir : un modèle qui prédit toujours la classe majoritaire l'optimise sans
# rien apprendre. Le MCC reste honnête dans ce cas.
METRIQUE_SELECTION = {
    Famille.REGRESSION: "r2_test",
    Famille.CLASSIFICATION: "roc_auc",
    Famille.CLASSIFICATION_DESEQUILIBREE: "mcc",
}

STATUT_VALIDE = "MODELE_VALIDE"
STATUT_HYPOTHESES_VIOLEES = "HYPOTHESES_VIOLEES"
STATUT_AUCUN_UTILE = "AUCUN_MODELE_UTILE"
