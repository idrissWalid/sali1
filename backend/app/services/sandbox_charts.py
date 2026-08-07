"""Helper `emit_chart` mis à disposition du code généré, dans la sandbox.

Ce module a deux vies :

1. **Injecté verbatim** en préambule du code exécuté dans la sandbox (voir
   `chart_spec.injectable_source()`). L'injection, plutôt qu'un `COPY` dans
   l'image Docker, évite d'imposer un `docker build` : une image sandbox déjà
   construite gagne `emit_chart` sans être reconstruite.
2. **Importé normalement** par le repli local d'exécution et par les tests.

Le transport se fait par stdout, une ligne par graphique préfixée par un
sentinelle : c'est le seul canal que le runner de la sandbox relaie déjà tel
quel, quelle que soit la version de l'image en place.

Le contrat de sortie est décrit dans `chart_spec.py`. Toute la logique de
lisibilité (plafond de catégories, échantillonnage, repli en tuile de
statistique) vit ici, donc en amont du rendu : un graphique illisible ne doit
même pas arriver jusqu'au navigateur.
"""

import base64
import json
import math

SALI_CHART_PREFIX = "<<<SALI_CHART>>>"
SALI_DATASET_PREFIX = "<<<SALI_DATASET>>>"

# Un jeu de données modifié repart par le même canal que les graphiques. Le CSV
# est encodé en base64 : il contient des retours à la ligne, qui casseraient le
# découpage ligne par ligne de la sortie.
MAX_DATASET_MO = 15

# Plafonds de lisibilité. Au-delà, un graphique cesse d'être lisible bien avant
# de cesser d'être calculable : on replie, on échantillonne ou on change de forme.
MAX_CATEGORIES = 30        # barres : au-delà les libellés se chevauchent
MAX_POINTS_LINE = 400      # courbes : au-delà les points sont sous le pixel
MAX_POINTS_SCATTER = 1500  # nuages : au-delà c'est une tache
MAX_SERIES = 8             # plafond de la palette catégorielle
MAX_SERIES_SCATTER = 3     # formes « toutes paires » : cap validé du nuancier
MAX_PIE_SLICES = 6         # part-de-tout d'un coup d'œil
MAX_BOX_GROUPS = 20
MAX_HEATMAP_CELLS = 900
MAX_TABLE_ROWS = 30        # tableau texte : au-delà, personne ne lit

KINDS = {
    "bar", "column", "line", "area", "scatter", "pie",
    "box", "heatmap", "stat",
}

OTHER_LABEL = "Autres"

# Paramètres réellement pris en compte.
PARAMETRES_EMIT_CHART = (
    "kind", "data", "x", "y", "title", "x_label", "y_label",
    "series_labels", "note", "emphasis", "stacked", "y_format",
)

# Arguments de style hérités de matplotlib/seaborn, que le code généré ajoute
# par réflexe. Les honorer n'aurait pas de sens — couleurs, tailles et styles
# viennent du thème validé, c'est précisément ce qui garantit la lisibilité —
# mais échouer dessus coûterait trois tentatives d'autocorrection pour un
# argument décoratif. Ils sont donc acceptés et ignorés.
PARAMETRES_DE_STYLE_IGNORES = {
    "color", "colors", "couleur", "couleurs", "palette", "cmap", "colormap",
    "style", "theme", "figsize", "dpi", "width", "height", "alpha",
    "linewidth", "lw", "linestyle", "marker", "markersize",
    "grid", "legend", "ax", "fig", "rotation", "fontsize", "label",
}


class ChartError(ValueError):
    """Erreur d'usage d'`emit_chart`, remontée telle quelle à l'autocorrection."""


# ── Normalisation des valeurs ────────────────────────────────────────────────

def _clean(value):
    """Rend une valeur sérialisable en JSON strict (ni NaN, ni Inf, ni numpy)."""
    if value is None:
        return None
    # numpy / pandas scalars : exposent .item()
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes, list, tuple, dict)):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int,)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value
    # Dates (datetime, pandas.Timestamp, numpy.datetime64 converti)
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass
    try:
        if value != value:  # NaN/NaT ne sont pas égaux à eux-mêmes
            return None
    except Exception:
        pass
    return str(value)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _to_records(data):
    """Convertit DataFrame / Series / dict de listes / liste de dicts en records.

    Retourne (records, colonnes) où `records` est une liste de dicts déjà
    nettoyés et `colonnes` préserve l'ordre d'origine.
    """
    if data is None:
        raise ChartError("emit_chart : l'argument `data` est obligatoire.")

    # pandas.DataFrame — détecté par attributs pour ne pas imposer l'import
    if hasattr(data, "to_dict") and hasattr(data, "columns"):
        columns = [str(c) for c in data.columns]
        raw = data.to_dict(orient="records")
        records = [
            {str(k): _clean(v) for k, v in row.items()}
            for row in raw
        ]
        return records, columns

    # pandas.Series — l'index devient une colonne
    if hasattr(data, "to_dict") and hasattr(data, "index") and hasattr(data, "name"):
        name = str(data.name) if data.name is not None else "valeur"
        index_name = str(getattr(data.index, "name", None) or "categorie")
        if index_name == name:
            index_name = index_name + "_"
        records = [
            {index_name: _clean(k), name: _clean(v)}
            for k, v in data.to_dict().items()
        ]
        return records, [index_name, name]

    if isinstance(data, dict):
        # dict de listes (format « colonnes »)
        if data and all(isinstance(v, (list, tuple)) for v in data.values()):
            columns = [str(c) for c in data.keys()]
            length = min(len(v) for v in data.values())
            records = [
                {str(c): _clean(list(data[c])[i]) for c in data}
                for i in range(length)
            ]
            return records, columns
        # dict simple {catégorie: valeur}
        records = [
            {"categorie": _clean(k), "valeur": _clean(v)}
            for k, v in data.items()
        ]
        return records, ["categorie", "valeur"]

    if isinstance(data, (list, tuple)):
        if not data:
            raise ChartError("emit_chart : `data` est vide, rien à tracer.")
        if all(isinstance(row, dict) for row in data):
            columns = []
            for row in data:
                for key in row:
                    if str(key) not in columns:
                        columns.append(str(key))
            records = [{str(k): _clean(v) for k, v in row.items()} for row in data]
            return records, columns
        raise ChartError(
            "emit_chart : une liste doit contenir des dictionnaires "
            "(un par point), ex. [{'mois': 'Jan', 'ventes': 12}, ...]."
        )

    raise ChartError(
        "emit_chart : type de `data` non supporté — passe un DataFrame, "
        "une Series, un dict de listes ou une liste de dictionnaires."
    )


# ── Réduction : ce qui rend un graphique lisible ─────────────────────────────

def _fold_categories(records, x_key, series_keys, limit):
    """Garde les `limit` plus grosses catégories, somme le reste en « Autres ».

    Renvoie (records, nombre_replié). Trier puis replier est ce qui distingue un
    graphique à 30 barres d'un graphique à 300 barres illisibles.
    """
    if len(records) <= limit:
        return records, 0

    def magnitude(row):
        total = 0.0
        for key in series_keys:
            value = row.get(key)
            if _is_number(value):
                total += abs(value)
        return total

    ordered = sorted(records, key=magnitude, reverse=True)
    kept, tail = ordered[:limit], ordered[limit:]

    other = {x_key: OTHER_LABEL}
    for key in series_keys:
        total = sum(row.get(key) for row in tail if _is_number(row.get(key)))
        other[key] = total
    kept.append(other)
    return kept, len(tail)


def _downsample(records, limit):
    """Échantillonne à pas régulier en gardant toujours le dernier point.

    Le pas régulier préserve la forme de la courbe ; garder le dernier point
    préserve la valeur que le lecteur cherche en premier (le niveau actuel).
    """
    if len(records) <= limit:
        return records, 0
    step = len(records) / float(limit)
    sampled = [records[int(i * step)] for i in range(limit)]
    if sampled[-1] is not records[-1]:
        sampled[-1] = records[-1]
    return sampled, len(records)


# ── Construction de la spec ──────────────────────────────────────────────────

def build_chart_spec(
    kind,
    data,
    x=None,
    y=None,
    title=None,
    x_label=None,
    y_label=None,
    series_labels=None,
    note=None,
    emphasis=None,
    stacked=False,
    y_format="number",
):
    """Construit la spec JSON d'un graphique. Voir `emit_chart` pour les arguments."""
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ChartError(
            "emit_chart : `kind` doit valoir l'un de " + ", ".join(sorted(KINDS))
            + " (reçu : " + repr(kind) + ")."
        )

    records, columns = _to_records(data)
    if not records:
        raise ChartError("emit_chart : `data` ne contient aucune ligne.")

    # Colonne d'abscisse : explicite, sinon la première colonne.
    x_key = str(x) if x is not None else columns[0]
    if x_key not in columns:
        raise ChartError(
            "emit_chart : la colonne x=" + repr(x_key) + " est absente des données "
            "(colonnes disponibles : " + ", ".join(columns) + ")."
        )

    # Colonnes de séries : explicites, sinon toutes les colonnes numériques.
    if y is None:
        series_keys = [
            c for c in columns
            if c != x_key and any(_is_number(row.get(c)) for row in records)
        ]
    elif isinstance(y, (list, tuple)):
        series_keys = [str(k) for k in y]
    else:
        series_keys = [str(y)]

    if not series_keys:
        raise ChartError(
            "emit_chart : aucune colonne de valeurs numériques trouvée. "
            "Précise y='nom_de_colonne'."
        )
    for key in series_keys:
        if key not in columns:
            raise ChartError(
                "emit_chart : la colonne y=" + repr(key) + " est absente des données "
                "(colonnes disponibles : " + ", ".join(columns) + ")."
            )

    # Plafond de séries : au-delà, la palette recycle des teintes et l'identité
    # des séries devient indevinable.
    series_cap = MAX_SERIES_SCATTER if kind == "scatter" else MAX_SERIES
    dropped_series = []
    if len(series_keys) > series_cap:
        dropped_series = series_keys[series_cap:]
        series_keys = series_keys[:series_cap]

    folded = 0
    sampled_from = 0

    if kind in ("bar", "column", "pie"):
        limit = MAX_PIE_SLICES if kind == "pie" else MAX_CATEGORIES
        records, folded = _fold_categories(records, x_key, series_keys, limit)
    elif kind in ("line", "area"):
        records, sampled_from = _downsample(records, MAX_POINTS_LINE)
    elif kind == "scatter":
        records, sampled_from = _downsample(records, MAX_POINTS_SCATTER)
    elif kind == "box":
        records = records[:MAX_BOX_GROUPS]
    elif kind == "heatmap":
        records = records[:MAX_HEATMAP_CELLS]

    # Une seule valeur : le nombre EST le graphique. Une barre unique ou un
    # camembert à deux parts se lisent moins bien qu'une tuile de statistique.
    if kind in ("bar", "column", "pie") and len(records) == 1 and len(series_keys) == 1:
        kind = "stat"

    x_type = "category"
    if kind in ("scatter", "heatmap"):
        x_type = "number" if all(_is_number(r.get(x_key)) for r in records) else "category"
    elif kind in ("line", "area"):
        values = [r.get(x_key) for r in records]
        if all(_is_number(v) for v in values):
            x_type = "number"
        elif any(isinstance(v, str) and len(v) >= 8 and v[:4].isdigit() for v in values):
            x_type = "time"

    labels = {}
    if series_labels:
        if isinstance(series_labels, dict):
            labels = {str(k): str(v) for k, v in series_labels.items()}
        elif isinstance(series_labels, (list, tuple)):
            labels = {
                key: str(label)
                for key, label in zip(series_keys, series_labels)
            }

    # Ne conserver que les colonnes utilisées : le reste alourdirait la réponse
    # sans jamais être affiché.
    kept_keys = [x_key] + series_keys
    if kind == "box":
        kept_keys += ["min", "q1", "mediane", "median", "q3", "max", "outliers"]
    if kind == "heatmap" and y is not None and not isinstance(y, (list, tuple)):
        kept_keys += ["v", "valeur"]
    data_out = [
        {k: row.get(k) for k in kept_keys if k in row}
        for row in records
    ]

    spec = {
        "v": 1,
        "kind": kind,
        "title": str(title) if title else None,
        "note": str(note) if note else None,
        "x": {
            "key": x_key,
            "label": str(x_label) if x_label else x_key,
            "type": x_type,
        },
        "y": {
            "label": str(y_label) if y_label else (
                labels.get(series_keys[0], series_keys[0]) if len(series_keys) == 1 else None
            ),
            "format": str(y_format or "number"),
        },
        "series": [
            {"key": key, "label": labels.get(key, key)}
            for key in series_keys
        ],
        "data": data_out,
        "stacked": bool(stacked),
        "emphasis": str(emphasis) if emphasis else None,
    }

    reductions = []
    if folded:
        reductions.append(
            str(folded) + " catégories de faible poids regroupées sous « "
            + OTHER_LABEL + " »"
        )
    if sampled_from:
        reductions.append(
            "série échantillonnée de " + str(sampled_from) + " à "
            + str(len(data_out)) + " points"
        )
    if dropped_series:
        reductions.append("séries non affichées : " + ", ".join(dropped_series))
    if reductions:
        spec["reductions"] = reductions

    return spec


def emit_dataset(df):
    """Renvoie le jeu de données modifié pour qu'il remplace celui de la session.

    Le sandbox est isolé : sans cet appel, un DataFrame transformé mourrait avec
    le container. Le code de transformation doit donc terminer par
    `emit_dataset(df)`, faute de quoi rien n'est enregistré.
    """
    if not hasattr(df, "to_csv"):
        raise ChartError(
            "emit_dataset : passe un DataFrame pandas (reçu : "
            + type(df).__name__ + ")."
        )
    if len(df.columns) == 0:
        raise ChartError("emit_dataset : le tableau n'a plus aucune colonne.")

    csv = df.to_csv(index=False).encode("utf-8")
    if len(csv) > MAX_DATASET_MO * 1024 * 1024:
        raise ChartError(
            "emit_dataset : tableau trop volumineux (" + str(len(csv) // (1024 * 1024))
            + " Mo, maximum " + str(MAX_DATASET_MO) + " Mo)."
        )

    print(SALI_DATASET_PREFIX + base64.b64encode(csv).decode("ascii"))
    return {"rows": len(df), "columns": len(df.columns)}


def markdown_table(data, max_rows=MAX_TABLE_ROWS):
    """Formate un tableau en markdown, sans dépendance externe.

    `DataFrame.to_markdown()` exige `tabulate`, absent de l'image sandbox : le
    code généré échouerait à l'exécution et consommerait les tentatives
    d'autocorrection pour une question de mise en forme. Le rendu est ici du
    markdown, donc affiché comme un vrai tableau dans la conversation.
    """
    records, columns = _to_records(data)
    if not records:
        return ""

    tronque = len(records) > max_rows
    visibles = records[:max_rows]

    def cellule(valeur):
        if valeur is None:
            return ""
        if isinstance(valeur, float):
            # Arrondi d'affichage : les décimales au-delà allongent la colonne
            # sans rien apprendre.
            valeur = round(valeur, 4)
            if valeur == int(valeur):
                return str(int(valeur))
        # Le pipe est le séparateur de colonnes : non échappé, il casse la ligne.
        return str(valeur).replace("|", "\\|")

    lignes = ["| " + " | ".join(str(c) for c in columns) + " |"]
    alignements = []
    for colonne in columns:
        numerique = any(_is_number(row.get(colonne)) for row in visibles)
        alignements.append("---:" if numerique else "---")
    lignes.append("| " + " | ".join(alignements) + " |")
    for row in visibles:
        lignes.append("| " + " | ".join(cellule(row.get(c)) for c in columns) + " |")

    if tronque:
        lignes.append("")
        lignes.append(
            "_" + str(max_rows) + " premières lignes sur " + str(len(records)) + "._"
        )
    return "\n".join(lignes)


def emit_chart(
    kind,
    data,
    x=None,
    y=None,
    title=None,
    x_label=None,
    y_label=None,
    series_labels=None,
    note=None,
    emphasis=None,
    stacked=False,
    y_format="number",
    **extra,
):
    """Émet un graphique interactif, rendu côté navigateur.

    Args:
        kind: bar | column | line | area | scatter | pie | box | heatmap | stat
        data: DataFrame, Series, dict de listes ou liste de dictionnaires
        x: colonne d'abscisse (défaut : la première colonne)
        y: colonne ou liste de colonnes de valeurs (défaut : toutes les numériques)
        title: titre du graphique
        x_label / y_label: libellés d'axes (unité comprise, ex. "Ventes (FCFA)")
        series_labels: dict {colonne: libellé} ou liste de libellés
        note: précision affichée sous le graphique
        emphasis: colonne à mettre en avant, les autres passent en gris
        stacked: empile les séries (part-de-tout)
        y_format: number | percent | currency

    Les arguments de style de matplotlib/seaborn (color, figsize, alpha…) sont
    acceptés puis ignorés : l'apparence vient du thème. Tout autre nom inconnu
    lève une erreur nommant les paramètres valides — une faute de frappe sur
    `title` ne doit pas passer inaperçue.

    Renvoie la spec émise (utile en test ; le code généré peut l'ignorer).
    """
    inconnus = sorted(k for k in extra if k not in PARAMETRES_DE_STYLE_IGNORES)
    if inconnus:
        raise ChartError(
            "emit_chart : paramètre(s) inconnu(s) : " + ", ".join(inconnus)
            + ". Paramètres acceptés : " + ", ".join(PARAMETRES_EMIT_CHART) + "."
        )

    spec = build_chart_spec(
        kind=kind, data=data, x=x, y=y, title=title,
        x_label=x_label, y_label=y_label, series_labels=series_labels,
        note=note, emphasis=emphasis, stacked=stacked, y_format=y_format,
    )
    print(SALI_CHART_PREFIX + json.dumps(spec, ensure_ascii=False))
    return spec
