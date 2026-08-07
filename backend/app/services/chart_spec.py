"""Transport des graphiques structurés entre la sandbox et le navigateur.

La sandbox n'a qu'un canal de sortie fiable et indépendant de la version de
l'image Docker en place : stdout. `emit_chart` (voir `sandbox_charts.py`) y
écrit une ligne préfixée par un sentinelle ; ce module réinjecte le helper dans
le code exécuté, puis extrait ces lignes de la sortie avant qu'elle ne parte à
l'interprétation du modèle.

Contrat d'une spec (v1) :

    {
      "v": 1,
      "kind": "bar|column|line|area|scatter|pie|box|heatmap|stat",
      "title": str|null,
      "note": str|null,
      "x": {"key": str, "label": str, "type": "category|number|time"},
      "y": {"label": str|null, "format": "number|percent|currency"},
      "series": [{"key": str, "label": str}],
      "data": [{...}],
      "stacked": bool,
      "emphasis": str|null,
      "reductions": [str]        // repliements/échantillonnages appliqués
    }
"""

import base64
import json
import os

from app.services.sandbox_charts import SALI_CHART_PREFIX, SALI_DATASET_PREFIX

_HELPER_PATH = os.path.join(os.path.dirname(__file__), "sandbox_charts.py")

# Garde-fous à la réception. La ligne extraite vient d'un code écrit par un
# modèle : elle est traitée comme une entrée non fiable, jamais comme une
# structure garantie.
MAX_CHARTS_PER_MESSAGE = 6
MAX_POINTS_PER_CHART = 2000
MAX_SERIES_PER_CHART = 8
_VALID_KINDS = {"bar", "column", "line", "area", "scatter", "pie", "box", "heatmap", "stat"}


# Consigne partagée par tous les prompts qui font produire du code traçant des
# graphiques. C'est le vrai levier de lisibilité : ce qui n'est pas agrégé ni
# trié en amont arrive illisible à l'écran, quel que soit le moteur de rendu.
CONSIGNE_EMIT_CHART = """RÈGLES DE VISUALISATION (impératives) :
Pour tout graphique destiné à l'utilisateur, appelle `emit_chart(...)` — déjà
disponible, rien à importer. Il rend un graphique interactif, lisible et adapté
au thème. N'utilise PAS matplotlib/seaborn pour ces graphiques.

emit_chart(kind, data, x=..., y=..., title=..., x_label=..., y_label=...)
  kind    : "column" (comparer des catégories), "bar" (idem, libellés longs),
            "line" (évolution dans le temps), "area" (une seule série cumulée),
            "scatter" (relation entre deux variables numériques),
            "pie" (part-de-tout, 6 parts maximum),
            "box" (distribution : colonnes min, q1, mediane, q3, max),
            "heatmap" (grille de valeurs : colonnes x, y et v)
  data    : un DataFrame **déjà agrégé** (ou une liste de dictionnaires)
  x       : colonne d'abscisse ; y : colonne(s) de valeurs
  autres  : title, x_label, y_label (avec l'unité), series_labels, note,
            emphasis="colonne" (met une série en avant, les autres en gris),
            stacked=True (part-de-tout), y_format="percent"|"currency"

Cette liste est exhaustive : il n'existe aucun autre paramètre. Les couleurs, la
taille, la police et le style sont imposés par le thème de l'application (et
s'adaptent au mode clair/sombre) — ne passe ni `color`, ni `palette`, ni
`figsize`, ils seraient sans effet.

Ce qui rend un graphique lisible, à faire AVANT d'appeler emit_chart :
1. Agrège toujours (`groupby(...).agg(...)`) — ne trace jamais des milliers de
   lignes brutes ; trie les catégories par valeur décroissante.
2. Un graphique = une idée. Deux grandeurs d'échelles différentes = deux appels
   à emit_chart, jamais deux axes verticaux sur un même graphique.
3. Au plus 8 séries (3 pour un nuage de points). Au-delà, regroupe le reste.
4. Donne toujours un titre explicite et des libellés d'axes avec leur unité.
5. Si une seule série porte le message, passe `emphasis` avec son nom.
6. Arrondis les valeurs affichées (`round(x, 2)`) : les décimales inutiles
   allongent les étiquettes sans rien apprendre.

matplotlib reste réservé aux figures de diagnostic sans équivalent (résidus,
matrice de confusion, courbe ROC) : elles seront jointes en image.

Pour afficher un tableau, utilise `print(markdown_table(df))` — également
disponible sans import. N'utilise PAS `to_markdown()`, dont la dépendance
`tabulate` est absente de l'environnement d'exécution.
"""


# Consigne des transformations de données. La contrainte décisive est la
# dernière ligne : sans `emit_dataset(df)`, le tableau modifié meurt avec le
# container et l'utilisateur croit avoir corrigé ses données sans que rien
# n'ait changé.
CONSIGNE_TRANSFORMATION = """RÈGLES DE MODIFICATION (impératives) :
Le dataframe est dans `df`. Applique EXACTEMENT la modification demandée, puis
termine par `emit_dataset(df)` — sans cet appel, rien n'est enregistré.

1. Ne touche à rien d'autre : aucune colonne, aucune ligne, aucun type qui ne
   soit visé par la demande. L'utilisateur ne verra pas ton code, il ne pourra
   pas repérer un effet de bord.
2. Conserve l'ordre des colonnes et l'ordre des lignes, sauf demande contraire.
3. Si la demande est impossible en l'état (colonne absente, valeur introuvable),
   lève une exception avec un message explicite plutôt que de deviner une
   intention voisine.
4. Affiche un résumé court et factuel de ce qui a changé, avec des nombres
   calculés — par exemple :
   `print("Lignes supprimées :", avant - len(df))`
   `print("Colonne renommée : vent -> ventes")`
   N'affiche pas le tableau entier : il est enregistré, pas commenté.
5. Ne trace aucun graphique, sauf demande explicite.
"""


def injectable_source() -> str:
    """Source du helper à préfixer au code exécuté dans la sandbox.

    Injecter plutôt que copier dans l'image évite d'imposer un `docker build`
    aux installations existantes : le code injecté voyage avec chaque exécution.
    """
    with open(_HELPER_PATH, "r", encoding="utf-8") as handle:
        return handle.read()


def prelude_snippet() -> str:
    """Injection du helper en **une seule ligne** de code exécuté.

    Concaténer la source telle quelle décalerait de quelques centaines de lignes
    tous les numéros de ligne des tracebacks — ceux-là mêmes qui repartent à
    l'autocorrection, qui compte les lignes du code qu'elle a écrit.
    """
    return "exec(compile({}, 'sali_charts', 'exec'))\n".format(repr(injectable_source()))


def extract_charts(output: str) -> tuple[list[dict], str]:
    """Sépare les specs de graphiques du reste de la sortie texte.

    Renvoie (specs, sortie_nettoyée). La sortie nettoyée est celle qui part à
    l'interprétation du modèle : y laisser le JSON gaspillerait le budget de
    contexte et polluerait la réponse rédigée.
    """
    if not output or SALI_CHART_PREFIX not in output:
        return [], output or ""

    charts: list[dict] = []
    kept_lines: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith(SALI_CHART_PREFIX):
            kept_lines.append(line)
            continue
        payload = stripped[len(SALI_CHART_PREFIX):]
        try:
            spec = json.loads(payload)
        except json.JSONDecodeError:
            continue  # ligne tronquée : on la laisse tomber sans casser la réponse
        spec = _sanitize(spec)
        if spec:
            charts.append(spec)

    return charts[:MAX_CHARTS_PER_MESSAGE], "\n".join(kept_lines).strip()


def extract_dataset(output: str) -> tuple[bytes | None, str]:
    """Sépare le jeu de données modifié du reste de la sortie texte.

    Renvoie (csv_bytes|None, sortie_nettoyée). Le dernier appel l'emporte : un
    code qui émettrait plusieurs états successifs livre son état final.
    """
    if not output or SALI_DATASET_PREFIX not in output:
        return None, output or ""

    csv_bytes = None
    kept_lines: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith(SALI_DATASET_PREFIX):
            kept_lines.append(line)
            continue
        try:
            csv_bytes = base64.b64decode(stripped[len(SALI_DATASET_PREFIX):], validate=True)
        except Exception:
            continue  # ligne tronquée : on ne remplace pas les données là-dessus

    return csv_bytes, "\n".join(kept_lines).strip()


def _sanitize(spec) -> dict | None:
    """Ne laisse passer qu'une spec structurellement exploitable par le rendu."""
    if not isinstance(spec, dict):
        return None
    if spec.get("kind") not in _VALID_KINDS:
        return None

    data = spec.get("data")
    if not isinstance(data, list) or not data:
        return None
    data = [row for row in data if isinstance(row, dict)][:MAX_POINTS_PER_CHART]
    if not data:
        return None

    series = spec.get("series")
    if not isinstance(series, list):
        return None
    series = [
        {"key": str(s.get("key")), "label": str(s.get("label") or s.get("key"))}
        for s in series
        if isinstance(s, dict) and s.get("key") is not None
    ][:MAX_SERIES_PER_CHART]
    if not series:
        return None

    axis_x = spec.get("x") if isinstance(spec.get("x"), dict) else {}
    axis_y = spec.get("y") if isinstance(spec.get("y"), dict) else {}
    x_key = str(axis_x.get("key") or "x")

    return {
        "v": 1,
        "kind": spec["kind"],
        "title": _text(spec.get("title")),
        "note": _text(spec.get("note")),
        "x": {
            "key": x_key,
            "label": _text(axis_x.get("label")) or x_key,
            "type": axis_x.get("type") if axis_x.get("type") in ("category", "number", "time") else "category",
        },
        "y": {
            "label": _text(axis_y.get("label")),
            "format": axis_y.get("format") if axis_y.get("format") in ("number", "percent", "currency") else "number",
        },
        "series": series,
        "band": {
            "key": str(spec["band"].get("key")),
            "label": _text(spec["band"].get("label")) or "Intervalle",
        } if isinstance(spec.get("band"), dict) and spec["band"].get("key") else None,
        "data": data,
        "stacked": bool(spec.get("stacked")),
        "emphasis": _text(spec.get("emphasis")),
        "reductions": [str(r) for r in spec.get("reductions", [])][:5]
        if isinstance(spec.get("reductions"), list) else [],
    }


def chart_from_timeseries_report(report: dict) -> dict | None:
    """Construit la spec « historique + prévision + IC 95 % » d'un rapport de série.

    Le pipeline temporel produit déjà un `metrics.json` structuré : inutile de
    demander au modèle un graphique en plus, la spec se déduit du rapport. La
    bande d'incertitude est portée par une série `ic` dont chaque point est un
    couple [bas, haut] — la convention que Recharts attend pour une aire.
    """
    if not isinstance(report, dict):
        return None
    historique = report.get("historique") or []
    prevision = report.get("prevision") or []
    if not historique and not prevision:
        return None

    points = []
    for ligne in historique:
        if not isinstance(ligne, dict):
            continue
        points.append({"date": ligne.get("date"), "historique": ligne.get("valeur")})

    # Le premier point de prévision reprend la dernière valeur observée, sinon
    # les deux courbes apparaissent séparées par un trou d'une période.
    if points and prevision:
        points[-1]["prevue"] = points[-1].get("historique")

    for ligne in prevision:
        if not isinstance(ligne, dict):
            continue
        point = {"date": ligne.get("date"), "prevue": ligne.get("valeur_prevue")}
        bas, haut = ligne.get("ic_bas"), ligne.get("ic_haut")
        if bas is not None and haut is not None:
            point["ic"] = [bas, haut]
        points.append(point)

    points = [p for p in points if p.get("date")]
    if not points:
        return None

    from app.services.sandbox_charts import MAX_POINTS_LINE, _downsample

    points, echantillonne = _downsample(points, MAX_POINTS_LINE)

    modele = (report.get("modele") or {}).get("type") if isinstance(report.get("modele"), dict) else None
    variable = report.get("variable") or report.get("colonne_valeur") or "Valeur"

    spec = {
        "v": 1,
        "kind": "line",
        "title": f"{variable} — historique et prévision"
                 + (f" ({modele})" if modele else ""),
        "note": None,
        "x": {"key": "date", "label": "Date", "type": "time"},
        "y": {"label": str(variable), "format": "number"},
        "series": [
            {"key": "historique", "label": "Historique"},
            {"key": "prevue", "label": "Prévision"},
        ],
        "band": {"key": "ic", "label": "Intervalle de confiance 95 %"},
        "data": points,
        "stacked": False,
        "emphasis": None,
        "reductions": (
            [f"série échantillonnée de {echantillonne} à {len(points)} points"]
            if echantillonne else []
        ),
    }
    return _sanitize(spec)


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:200] if text else None


def describe_for_llm(charts: list[dict]) -> str:
    """Résume les graphiques émis, pour que l'interprétation puisse s'y référer.

    Le modèle qui rédige la réponse ne voit pas les graphiques : sans ce résumé
    il écrit « voir le graphique » sans savoir ce qu'il montre.
    """
    if not charts:
        return ""
    lignes = []
    for chart in charts:
        series = ", ".join(s["label"] for s in chart["series"])
        titre = chart.get("title") or "sans titre"
        lignes.append(
            f"- {chart['kind']} « {titre} » : {series} en fonction de "
            f"{chart['x']['label']} ({len(chart['data'])} points)"
        )
    return "Graphiques interactifs déjà affichés à l'utilisateur :\n" + "\n".join(lignes)
