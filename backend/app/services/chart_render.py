"""Rendu PNG d'une spec de graphique, pour les exports PDF/Word.

Les graphiques du chat sont interactifs et vivent dans le navigateur ; un
rapport, lui, ne transporte que des images. Cette passerelle rend chaque spec
avec matplotlib, sur fond blanc et avec la même palette que le rendu web, pour
qu'un export ressemble à ce que l'utilisateur a vu à l'écran.

Le rendu est délibérément sobre : grille discrète, axes fins, légende seulement
à partir de deux séries — les mêmes règles que côté web.
"""

import base64
import io
import logging

logger = logging.getLogger(__name__)

# Palette catégorielle, variante « surface claire » (validée : bande de clarté,
# plancher de chroma, séparation daltonisme). Même ordre de slots que le web :
# une série garde sa couleur du chat au rapport.
PALETTE = [
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
    "#e87ba4", "#008300", "#4a3aa7", "#e34948",
]
GRIS_ATTENUE = "#b9b8b2"   # séries reléguées au contexte (mode emphase)
ENCRE = "#0b0b0b"
ENCRE_SECONDAIRE = "#52514e"
GRILLE = "#e1e0d9"

MAX_LABEL = 22  # au-delà, un libellé d'axe est tronqué plutôt que superposé


def render_specs_to_png(specs: list) -> list:
    """Rend une liste de specs en PNG base64. Une spec illisible est ignorée."""
    images = []
    for spec in specs or []:
        png = render_spec_to_png(spec)
        if png:
            images.append(png)
    return images


def render_spec_to_png(spec: dict) -> str | None:
    """Rend une spec en PNG base64, ou None si le type n'a pas d'équivalent image."""
    if not isinstance(spec, dict) or spec.get("kind") in (None, "stat"):
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - matplotlib absent
        logger.warning("Rendu PNG impossible (matplotlib indisponible) : %s", exc)
        return None

    try:
        fig, ax = plt.subplots(figsize=(9, 5))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        kind = spec["kind"]
        data = spec.get("data") or []
        series = spec.get("series") or []
        x_key = spec.get("x", {}).get("key", "x")
        emphasis = spec.get("emphasis")

        couleurs = {
            s["key"]: (
                PALETTE[i % len(PALETTE)]
                if not emphasis or s["key"] == emphasis
                else GRIS_ATTENUE
            )
            for i, s in enumerate(series)
        }

        abscisses = [_court(row.get(x_key)) for row in data]

        if kind == "pie":
            cle = series[0]["key"]
            valeurs = [_nombre(row.get(cle)) for row in data]
            ax.pie(
                valeurs, labels=abscisses, autopct="%1.1f%%",
                colors=PALETTE[: len(valeurs)],
                textprops={"color": ENCRE, "fontsize": 9},
                wedgeprops={"linewidth": 2, "edgecolor": "white"},
            )
            ax.axis("equal")
        elif kind in ("bar", "column"):
            _rendre_barres(ax, data, series, couleurs, abscisses, x_key,
                           horizontal=(kind == "bar"), empile=spec.get("stacked"))
        elif kind in ("line", "area"):
            for s in series:
                valeurs = [_nombre(row.get(s["key"])) for row in data]
                ax.plot(abscisses, valeurs, lw=2, color=couleurs[s["key"]],
                        label=s["label"], solid_capstyle="round")
                if kind == "area" and len(series) == 1:
                    ax.fill_between(range(len(valeurs)),
                                    [v or 0 for v in valeurs],
                                    color=couleurs[s["key"]], alpha=0.1)
        elif kind == "scatter":
            for s in series:
                ax.scatter(
                    [_nombre(row.get(x_key)) for row in data],
                    [_nombre(row.get(s["key"])) for row in data],
                    s=28, color=couleurs[s["key"]], label=s["label"],
                    edgecolors="white", linewidths=1.5, alpha=0.9,
                )
        elif kind == "box":
            groupes = [
                [v for v in (
                    _nombre(row.get("min")), _nombre(row.get("q1")),
                    _nombre(row.get("mediane") if row.get("mediane") is not None else row.get("median")),
                    _nombre(row.get("q3")), _nombre(row.get("max")),
                ) if v is not None]
                for row in data
            ]
            groupes = [g for g in groupes if g]
            if not groupes:
                plt.close(fig)
                return None
            boites = ax.boxplot(groupes, labels=abscisses[: len(groupes)], patch_artist=True)
            for patch in boites["boxes"]:
                patch.set_facecolor(PALETTE[0])
                patch.set_alpha(0.35)
                patch.set_edgecolor(PALETTE[0])
        elif kind == "heatmap":
            image, lignes, colonnes = _grille_heatmap(data, x_key, series)
            if image is None:
                plt.close(fig)
                return None
            carte = ax.imshow(image, cmap="Blues", aspect="auto")
            ax.set_xticks(range(len(colonnes)))
            ax.set_xticklabels([_court(c) for c in colonnes], rotation=45, ha="right")
            ax.set_yticks(range(len(lignes)))
            ax.set_yticklabels([_court(l) for l in lignes])
            fig.colorbar(carte, ax=ax, shrink=0.8)
        else:
            plt.close(fig)
            return None

        _habiller(ax, spec, kind, len(series), len(abscisses))
        fig.tight_layout()

        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=160, bbox_inches="tight",
                    facecolor="white", edgecolor="none")
        plt.close(fig)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")
    except Exception as exc:
        logger.warning("Rendu PNG du graphique « %s » échoué : %s", spec.get("title"), exc)
        try:
            plt.close("all")
        except Exception:
            pass
        return None


def _rendre_barres(ax, data, series, couleurs, abscisses, x_key, horizontal, empile):
    positions = range(len(data))
    if empile or len(series) == 1:
        cumul = [0.0] * len(data)
        for s in series:
            valeurs = [_nombre(row.get(s["key"])) or 0 for row in data]
            if horizontal:
                ax.barh(positions, valeurs, left=cumul, height=0.62,
                        color=couleurs[s["key"]], label=s["label"])
            else:
                ax.bar(positions, valeurs, bottom=cumul, width=0.62,
                       color=couleurs[s["key"]], label=s["label"])
            cumul = [c + v for c, v in zip(cumul, valeurs)]
    else:
        largeur = 0.8 / len(series)
        for i, s in enumerate(series):
            valeurs = [_nombre(row.get(s["key"])) or 0 for row in data]
            decale = [p - 0.4 + largeur * (i + 0.5) for p in positions]
            if horizontal:
                ax.barh(decale, valeurs, height=largeur * 0.88,
                        color=couleurs[s["key"]], label=s["label"])
            else:
                ax.bar(decale, valeurs, width=largeur * 0.88,
                       color=couleurs[s["key"]], label=s["label"])

    if horizontal:
        ax.set_yticks(list(positions))
        ax.set_yticklabels(abscisses)
        ax.invert_yaxis()
    else:
        ax.set_xticks(list(positions))
        ax.set_xticklabels(abscisses)


def _habiller(ax, spec, kind, nb_series, nb_points):
    """Titres, axes, grille, légende — la part « chrome » du graphique."""
    if spec.get("title"):
        ax.set_title(spec["title"], color=ENCRE, fontsize=12, pad=12, loc="left")

    if kind not in ("pie", "heatmap"):
        libelle_x = spec.get("x", {}).get("label")
        libelle_y = spec.get("y", {}).get("label")
        if kind == "bar":
            libelle_x, libelle_y = libelle_y, libelle_x
        if libelle_x:
            ax.set_xlabel(libelle_x, color=ENCRE_SECONDAIRE, fontsize=9)
        if libelle_y:
            ax.set_ylabel(libelle_y, color=ENCRE_SECONDAIRE, fontsize=9)

        # Grille sur le seul axe des valeurs : une grille croisée double le bruit
        # sans rien ajouter à la lecture.
        ax.grid(axis="x" if kind == "bar" else "y", color=GRILLE, lw=0.8)
        ax.set_axisbelow(True)
        for cote in ("top", "right"):
            ax.spines[cote].set_visible(False)
        for cote in ("left", "bottom"):
            ax.spines[cote].set_color(GRILLE)
        ax.tick_params(colors=ENCRE_SECONDAIRE, labelsize=9, length=0)

        # Libellés obliques dès qu'ils risquent de se toucher.
        if kind in ("bar",):
            pass
        elif nb_points > 6:
            for etiquette in ax.get_xticklabels():
                etiquette.set_rotation(35)
                etiquette.set_horizontalalignment("right")

    # Une seule série : le titre dit déjà ce qui est tracé, la légende ferait doublon.
    if nb_series > 1 and kind != "pie":
        ax.legend(frameon=False, fontsize=9, labelcolor=ENCRE_SECONDAIRE)


def _grille_heatmap(data, x_key, series):
    """Transforme des triplets (x, y, valeur) en matrice pour `imshow`."""
    cle_y = series[0]["key"] if series else None
    cle_v = "v" if any("v" in row for row in data) else "valeur"
    if not cle_y or not any(cle_v in row for row in data):
        return None, [], []

    colonnes, lignes = [], []
    for row in data:
        if row.get(x_key) not in colonnes:
            colonnes.append(row.get(x_key))
        if row.get(cle_y) not in lignes:
            lignes.append(row.get(cle_y))

    matrice = [[None] * len(colonnes) for _ in lignes]
    for row in data:
        i = lignes.index(row.get(cle_y))
        j = colonnes.index(row.get(x_key))
        matrice[i][j] = _nombre(row.get(cle_v))
    return matrice, lignes, colonnes


def _nombre(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _court(value):
    texte = "" if value is None else str(value)
    return texte if len(texte) <= MAX_LABEL else texte[: MAX_LABEL - 1] + "…"
