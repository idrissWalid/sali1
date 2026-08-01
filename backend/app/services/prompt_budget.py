"""prompt_budget.py — Construire les prompts DANS le budget du modèle choisi.

Deux backends très inégaux partagent les mêmes prompts : une API distante encaisse
des centaines de milliers de tokens, un modèle servi par la machine de
l'utilisateur tourne ici avec `num_ctx=4096`. Jusqu'ici la conciliation se faisait
EN AVAL, dans `ollama_service._trim_prompt`, qui coupe le prompt en son milieu. Sur
un contexte de données, cette coupe tombe au hasard dans un JSON : elle fait
disparaître les statistiques auxquelles les consignes finales, elles, se réfèrent
toujours. Le modèle reçoit alors une question sur des chiffres absents.

Ici on construit le prompt pour qu'il TIENNE, en retirant d'abord ce qui informe le
moins.

Ce que la mesure a montré (corpus réel de `data/uploads`, 24 fichiers profilés) :
le poste dominant n'est pas les statistiques (12,9 % du prompt) mais l'aperçu des
5 premières lignes (83,5 %). Sur un jeu de données textuel, cinq corps d'articles
pèsent 17 836 caractères — soit ~5 600 tokens rejoués à CHAQUE tour de chat, car
`get_data_context` est reconstruit à chaque message. Aucun de ces caractères
n'apprend quoi que ce soit de plus sur la structure du fichier. Les borner suffit à
retirer 76 % du volume, sur tous les backends : le gain est aussi une facture d'API
en moins.

L'aperçu n'est borné qu'à L'ENTRÉE DES PROMPTS. Celui qui est stocké en session et
affiché dans le tableau de bord reste intact : l'utilisateur, lui, veut voir ses
données en entier.
"""

import json
from dataclasses import dataclass

# Largeur au-delà de laquelle une cellule d'aperçu n'apprend plus rien sur la
# structure des données. 200 caractères laissent reconnaître un format de date, un
# identifiant, un libellé de catégorie ou le début d'un champ libre — ce que le
# modèle a besoin de savoir. Le corps complet d'un article, non.
LARGEUR_MAX_CELLULE = 200

# Marque une valeur écourtée. Explicite, pour que le modèle ne prenne pas la valeur
# tronquée pour la valeur réelle (« 2018-08-2 » au lieu de « 2018-08-22 »).
_MARQUE_COUPE = "… [valeur écourtée]"

# Statistiques réellement porteuses d'information par variable. `ydata-profiling`
# en produit beaucoup plus (histogrammes, quantiles fins, comptages de casse…) :
# les verser toutes dans le contexte coûte des tokens à chaque tour sans rien
# ajouter à ce que le modèle peut en dire.
_STATS_UTILES = (
    "type", "moyenne", "mediane", "ecart_type", "min", "max", "q1", "q3",
    "skewness", "kurtosis", "n_manquantes", "n_zeros", "n_valeurs_distinctes",
    "valeur_dominante", "frequence_dominante",
)


@dataclass(frozen=True)
class ProfilModele:
    """Ce qu'un modèle peut encaisser, indépendamment de son fournisseur.

    `consignes_denses` ne dit pas « c'est une API » mais « ce modèle sait suivre une
    méthodologie multi-étapes à gates bloquants » (cf. la spec SARIMA A–H de
    `model_specs`). Un 2 Md quantifié servi en local ne sait pas ; les modèles
    distants, même les petits, savent — d'où un axe distinct du budget.
    """

    nom: str
    budget_contexte: int
    consignes_denses: bool


# Un modèle local partage `num_ctx=4096` (~16 000 caractères) entre prompt système,
# historique, contexte de données et question. La moitié pour le contexte : au-delà,
# c'est la question de l'utilisateur elle-même qui se fait raccourcir en aval.
PROFIL_LOCAL = ProfilModele("local", budget_contexte=8_000, consignes_denses=False)

# Une API distante n'a pas de contrainte pratique à cette échelle. Le plafond reste
# fini : il borne le coût par tour, pas la capacité du modèle.
PROFIL_API = ProfilModele("api", budget_contexte=120_000, consignes_denses=True)


def est_local(model: str | None) -> bool:
    """Le modèle est-il servi par la machine de l'utilisateur (Ollama) ?

    Même convention de nommage que `gemini_service.complete_text`, seule source de
    vérité du routage : un préfixe « fournisseur/ » (« openai/gpt-4o ») ou un nom
    commençant par « gemini » désigne une API distante ; un nom nu (« qwen3.5:4b »)
    est un modèle local.
    """
    nom = (model or "").strip()
    return bool(nom) and "/" not in nom and not nom.startswith("gemini")


def profil_modele(model: str | None) -> ProfilModele:
    """Profil du modèle sélectionné. Un modèle inconnu ou absent est traité comme
    distant : c'est le défaut de l'application, et surestimer le budget d'un modèle
    local se paie en raccourcissement, pas en erreur."""
    return PROFIL_LOCAL if est_local(model) else PROFIL_API


def _borner_valeur(valeur, largeur_max: int):
    """Écourte une valeur textuelle trop large, laisse les autres intactes.

    Les nombres, booléens et `None` passent tels quels : leur écriture est déjà
    courte, et les convertir en texte pour les mesurer changerait le type que le
    modèle lit dans le JSON.
    """
    if not isinstance(valeur, str) or len(valeur) <= largeur_max:
        return valeur
    return valeur[:largeur_max].rstrip() + _MARQUE_COUPE


def apercu_borne(preview: list[dict] | None,
                 largeur_max: int = LARGEUR_MAX_CELLULE) -> list[dict]:
    """Aperçu dont chaque cellule est ramenée à une largeur lisible."""
    return [
        {cle: _borner_valeur(valeur, largeur_max) for cle, valeur in ligne.items()}
        for ligne in (preview or [])
    ]


def _tient(lignes: list[dict], budget: int) -> bool:
    return len(json.dumps(lignes, ensure_ascii=False, indent=2)) <= budget


def apercu_dans_budget(preview: list[dict] | None, budget: int,
                       largeur_max: int = LARGEUR_MAX_CELLULE) -> tuple[list[dict], int]:
    """Aperçu ramené sous `budget` caractères, avec le nombre de lignes retirées.

    Trois leviers, du moins au plus coûteux en information :

    1. borner les cellules en largeur — c'est là qu'est l'essentiel du volume ;
    2. retirer des LIGNES, jamais des colonnes : une ligne en moins reste un exemple
       complet de la structure, alors qu'une colonne en moins ferait croire au
       modèle qu'elle n'existe pas ;
    3. resserrer encore la largeur, si même une seule ligne ne rentre pas.

    Le troisième levier existe pour les tables LARGES : à 13 colonnes toutes
    textuelles, une ligne bornée à 200 caractères pèse déjà plus que le budget d'un
    modèle local, et s'arrêter au levier 2 supprimerait l'aperçu en entier. Or 30
    caractères par cellule suffisent encore à reconnaître une forme de date, un
    libellé ou un identifiant — ce que le modèle a besoin de savoir. Garder une
    ligne étroite vaut mieux que n'en garder aucune.
    """
    if not preview:
        return [], 0

    for largeur in (largeur_max, 80, 30):
        lignes = apercu_borne(preview, largeur)
        while lignes and not _tient(lignes, budget):
            lignes = lignes[:-1]
        if lignes:
            return lignes, len(preview) - len(lignes)

    return [], len(preview)


def bloc_apercu(preview: list[dict] | None, budget: int,
                largeur_max: int = LARGEUR_MAX_CELLULE) -> str:
    """Section « aperçu » d'un prompt, tenant dans `budget`, et qui DIT ce qu'elle
    a retiré.

    Annoncer l'omission importe autant que l'omission elle-même : sans mention, un
    aperçu vide se lit comme un fichier vide, et un aperçu de deux lignes comme un
    fichier de deux lignes.
    """
    total = len(preview or [])
    if not total:
        return "Aucun aperçu disponible."

    lignes, retirees = apercu_dans_budget(preview, budget, largeur_max)
    if not lignes:
        return (f"Aperçu omis : les {total} lignes d'exemple dépassent le budget de "
                f"contexte de ce modèle. Appuie-toi sur les statistiques ci-dessus.")

    corps = json.dumps(lignes, ensure_ascii=False, indent=2)
    if retirees:
        return (f"{corps}\n({retirees} ligne(s) d'aperçu sur {total} retirée(s) pour "
                f"tenir dans le contexte de ce modèle.)")
    return corps


def stats_essentielles(variables: dict | None) -> dict:
    """Statistiques par variable réduites à celles qui portent l'information.

    `get_data_context` versait jusqu'ici le dump `ydata-profiling` intégral à chaque
    tour de chat, là où `build_analysis_prompt` faisait déjà cette sélection : même
    donnée, deux volumes. Un seul filtre pour les deux.
    """
    return {
        nom: {cle: valeur for cle, valeur in (stats or {}).items() if cle in _STATS_UTILES}
        for nom, stats in (variables or {}).items()
    }
