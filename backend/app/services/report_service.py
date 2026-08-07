import io
import base64
import json
import logging
import re
from datetime import datetime
from app.services.gemini_service import complete_text
from app.core import config
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Image, HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pptx import Presentation
from pptx.util import Inches as PptxInches, Pt as PptxPt, Emu
from pptx.dml.color import RGBColor as PptxRGB
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

PRIMARY = HexColor("#1a73e8")
DARK = HexColor("#202124")   # titres
GRAY = HexColor("#5f6368")   # sous-titres, légendes, filets — même gris que l'export Word

logger = logging.getLogger(__name__)

# Sections attendues du rapport, dans l'ordre de rendu. Sert à la fois de contrat
# avec le modèle et de garde-fou : une clé absente de sa réponse ne doit pas
# faire échouer la génération.
SECTIONS_RAPPORT = [
    ("resume_executif", "Résumé exécutif"),
    ("description_donnees", "Description du jeu de données"),
    ("resultats", "Résultats analytiques"),
    ("conclusions", "Conclusions"),
    ("recommandations", "Recommandations"),
]


def _bloc_faits(profile: dict, stats: dict, models: list) -> str:
    """Chiffres vérifiables du jeu de données, mis en forme pour le prompt.

    Sans ce bloc, le modèle ne dispose que de l'analyse initiale et du fil de
    discussion : il y reprend des nombres de seconde main, déjà arrondis ou
    reformulés, et en invente le reste. Les statistiques sont ici celles
    calculées par ydata-profiling à l'ingestion — c'est la seule source du
    rapport qui ne soit pas une paraphrase.
    """
    profile = profile or {}
    stats = stats or {}
    overview = stats.get("dataset_overview", {})
    variables = stats.get("variables", {})

    lignes = [
        "CHIFFRES DU JEU DE DONNÉES (source : profilage automatique — à reprendre tels quels)",
        f"- Lignes : {profile.get('rows', overview.get('n_lignes', 'inconnu'))}",
        f"- Colonnes : {profile.get('columns', overview.get('n_variables', 'inconnu'))}",
    ]
    if profile.get("column_names"):
        lignes.append(f"- Noms des colonnes : {', '.join(map(str, profile['column_names']))}")
    if overview:
        lignes.append(
            f"- Doublons : {overview.get('n_doublons', 0)} ({overview.get('pct_doublons', 0)} %)"
        )
        lignes.append(
            f"- Valeurs manquantes : {overview.get('n_valeurs_manquantes_total', 0)} "
            f"({overview.get('pct_valeurs_manquantes_total', 0)} %)"
        )
        lignes.append(
            f"- Variables numériques : {overview.get('n_variables_numeriques', 0)} · "
            f"catégorielles : {overview.get('n_variables_categorielles', 0)}"
        )

    numeriques, categorielles = {}, {}
    for col, s in (variables or {}).items():
        if s.get("type") == "Numeric":
            numeriques[col] = {
                k: s[k] for k in
                ("moyenne", "mediane", "ecart_type", "min", "max", "q1", "q3",
                 "skewness", "n_manquantes", "n_valeurs_distinctes")
                if k in s
            }
        elif s.get("type") in ("Categorical", "Boolean"):
            categorielles[col] = {
                k: s[k] for k in
                ("n_valeurs_distinctes", "valeur_dominante", "frequence_dominante", "n_manquantes")
                if k in s
            }

    if numeriques:
        lignes.append("\nSTATISTIQUES DES VARIABLES NUMÉRIQUES :")
        lignes.append(json.dumps(numeriques, ensure_ascii=False, indent=2))
    if categorielles:
        lignes.append("\nSTATISTIQUES DES VARIABLES CATÉGORIELLES :")
        lignes.append(json.dumps(categorielles, ensure_ascii=False, indent=2))

    correlations = stats.get("correlations") or {}
    if correlations:
        lignes.append("\nCORRÉLATIONS :")
        lignes.append(json.dumps(correlations, ensure_ascii=False, indent=2))

    missing = stats.get("missing") or {}
    if missing:
        lignes.append("\nVALEURS MANQUANTES PAR COLONNE :")
        lignes.append(json.dumps(missing, ensure_ascii=False, indent=2))

    if models:
        lignes.append("\nMODÈLES ENTRAÎNÉS DANS LA SESSION :")
        for m in models:
            features = ", ".join(map(str, m.get("features") or [])) or "non précisées"
            lignes.append(
                f"- « {m.get('name')} » (type : {m.get('type')}) · variables : {features}"
            )
            if m.get("metrics"):
                lignes.append(f"  métriques : {json.dumps(m['metrics'], ensure_ascii=False)}")

    return "\n".join(lignes)


# ── Rédaction du rapport par le LLM ────────────────────────────
def draft_report_with_llm(
    filename: str,
    analysis_text: str,
    chat_history: list,
    title: str,
    institution: str,
    model: str | None = None,
    key_points: str = "",
    profile: dict | None = None,
    stats: dict | None = None,
    models: list | None = None,
) -> dict:
    """
    Demande au modèle de rédiger un rapport structuré à partir des éléments
    de la session, ancré sur les statistiques réelles du jeu de données.
    Retourne un dict avec les sections du rapport.
    """
    model = model or config.get_default_model()
    history_summary = "\n".join([
        f"[{m['role'].upper()}] {m['text'][:500]}"
        for m in chat_history
    ])

    # Les points clés dictés par l'utilisateur passent avant le reste : c'est la
    # seule consigne du rapport qui vienne de quelqu'un qui connaît le contexte
    # métier, que ni les statistiques ni le fil de discussion ne portent.
    bloc_consigne = ""
    if key_points.strip():
        bloc_consigne = f"""
CONSIGNE PRIORITAIRE DU COMMANDITAIRE :
{key_points.strip()}

Structure le rapport autour de cette demande : elle décide de ce qui est
développé et de ce qui reste accessoire. Si les données ne permettent pas d'y
répondre, dis-le explicitement dans les résultats plutôt que de la contourner.
"""

    prompt = f"""
Tu es un expert en rédaction de rapports analytiques institutionnels.

Voici les éléments d'une session d'analyse de données :

FICHIER ANALYSÉ : {filename}
TITRE DU RAPPORT : {title}
INSTITUTION : {institution}
{bloc_consigne}
{_bloc_faits(profile or {}, stats or {}, models or [])}

ANALYSE INITIALE :
{analysis_text}

ÉCHANGES DE LA SESSION :
{history_summary}

Rédige un rapport analytique complet, structuré et professionnel, directement
publiable dans un contexte institutionnel.

Règles de rédaction :
- Appuie chaque affirmation quantitative sur un chiffre du bloc ci-dessus, cité tel quel.
- N'invente aucune donnée : si une information manque, écris-le au lieu de l'estimer.
- Écris en texte brut, sans markdown (pas de **, #, ni de listes à puces).
- Rédige en français, en paragraphes suivis.

Retourne EXACTEMENT ce format JSON (sans markdown) :
{{
  "resume_executif": "3 à 5 phrases résumant les conclusions principales",
  "description_donnees": "Description complète du jeu de données : variables, dimensions, qualité, période couverte",
  "resultats": "Section principale des résultats analytiques, bien structurée en paragraphes. Minimum 200 mots.",
  "conclusions": "Conclusions clés et implications pratiques pour l'institution",
  "recommandations": "3 à 5 recommandations concrètes et actionnables numérotées"
}}
"""
    text = complete_text(prompt, model).strip()

    # Nettoyer les backticks si présents
    if text.startswith("```"):
        lignes = text.split("\n")
        text = "\n".join(lignes[1:-1] if lignes[-1].strip().startswith("```") else lignes[1:])

    try:
        sections = json.loads(text)
    except json.JSONDecodeError:
        # Le modèle a parlé mais pas en JSON : le texte reste exploitable comme
        # corps de rapport, alors qu'un échec ici perdrait tout l'appel.
        logger.warning("Rapport : réponse non-JSON du modèle %s, repli sur le texte brut.", model)
        sections = {"resultats": text}

    if not isinstance(sections, dict):
        sections = {"resultats": str(sections)}

    # Une section absente devient une mention explicite : mieux vaut un rapport
    # qui signale son trou qu'un KeyError au moment du rendu.
    return {
        cle: str(sections.get(cle) or "").strip() or "Section non renseignée par le modèle."
        for cle, _ in SECTIONS_RAPPORT
    }


# ── Génération PDF ──────────────────────────────────────────────
def build_pdf_report(
    title: str,
    institution: str,
    filename: str,
    analysis_text: str,
    messages: list,
    images_b64: list,
    model: str | None = None,
    key_points: str = "",
    profile: dict | None = None,
    stats: dict | None = None,
    models: list | None = None,
) -> bytes:
    sections = draft_report_with_llm(
        filename=filename,
        analysis_text=analysis_text,
        chat_history=messages,
        title=title,
        institution=institution,
        model=model,
        key_points=key_points,
        profile=profile,
        stats=stats,
        models=models,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2.5*cm, leftMargin=2.5*cm,
        topMargin=2.5*cm, bottomMargin=2.5*cm,
    )

    style_title = ParagraphStyle("T", fontSize=22, fontName="Helvetica-Bold",
                                  textColor=DARK, spaceAfter=6)
    style_sub   = ParagraphStyle("S", fontSize=11, fontName="Helvetica",
                                  textColor=GRAY, spaceAfter=4)
    style_sec   = ParagraphStyle("SE", fontSize=13, fontName="Helvetica-Bold",
                                  textColor=PRIMARY, spaceBefore=18, spaceAfter=8)
    style_body  = ParagraphStyle("B", fontSize=10, fontName="Helvetica",
                                  textColor=HexColor("#2d2d2d"), spaceAfter=6,
                                  leading=16, alignment=TA_JUSTIFY)
    style_cap   = ParagraphStyle("C", fontSize=8, fontName="Helvetica-Oblique",
                                  textColor=GRAY, spaceAfter=8, alignment=TA_CENTER)
    style_rec   = ParagraphStyle("R", fontSize=10, fontName="Helvetica",
                                  textColor=HexColor("#2d2d2d"), spaceAfter=4,
                                  leading=15, leftIndent=15)

    def add_section(elements, title, content):
        elements.append(Paragraph(title, style_sec))
        for line in content.split("\n"):
            line = line.strip()
            if line:
                elements.append(Paragraph(line, style_body))
            else:
                elements.append(Spacer(1, 4))

    elements = []

    # ── Page de garde ──────────────────────────────────────────
    elements.append(Spacer(1, 2*cm))
    elements.append(HRFlowable(width="100%", thickness=3, color=PRIMARY, spaceAfter=20))
    elements.append(Paragraph(title, style_title))
    elements.append(Spacer(1, 6))
    elements.append(Paragraph(institution, style_sub))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"Source analysée : {filename}", style_sub))
    elements.append(Paragraph(
        f"Date de génération : {datetime.now().strftime('%d %B %Y à %H:%M')}",
        style_sub))
    elements.append(HRFlowable(width="100%", thickness=1, color=GRAY, spaceAfter=20))
    elements.append(PageBreak())

    # ── Résumé exécutif ────────────────────────────────────────
    add_section(elements, "Résumé exécutif", sections["resume_executif"])

    # ── Description des données ────────────────────────────────
    add_section(elements, "Description du jeu de données", sections["description_donnees"])

    # ── Résultats ──────────────────────────────────────────────
    add_section(elements, "Résultats analytiques", sections["resultats"])

    # ── Visualisations ─────────────────────────────────────────
    if images_b64:
        elements.append(Paragraph("Visualisations", style_sec))
        for idx, img_b64 in enumerate(images_b64):
            try:
                buf = io.BytesIO(base64.b64decode(img_b64))
                elements.append(Image(buf, width=14*cm, height=8*cm))
                elements.append(Paragraph(f"Figure {idx + 1}", style_cap))
                elements.append(Spacer(1, 8))
            except Exception:
                pass

    # ── Conclusions ────────────────────────────────────────────
    add_section(elements, "Conclusions", sections["conclusions"])

    # ── Recommandations ────────────────────────────────────────
    elements.append(Paragraph("Recommandations", style_sec))
    for line in sections["recommandations"].split("\n"):
        line = line.strip()
        if line:
            elements.append(Paragraph(line, style_rec))

    # ── Pied de page ───────────────────────────────────────────
    elements.append(Spacer(1, 20))
    elements.append(HRFlowable(width="100%", thickness=1, color=GRAY, spaceAfter=8))
    elements.append(Paragraph(
        "Rapport généré par No-Code Data Intelligence · CITADEL Ouagadougou",
        style_cap))

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


# ── Génération Word ─────────────────────────────────────────────
def build_word_report(
    title: str,
    institution: str,
    filename: str,
    analysis_text: str,
    messages: list,
    images_b64: list,
    model: str | None = None,
    key_points: str = "",
    profile: dict | None = None,
    stats: dict | None = None,
    models: list | None = None,
) -> bytes:
    sections = draft_report_with_llm(
        filename=filename,
        analysis_text=analysis_text,
        chat_history=messages,
        title=title,
        institution=institution,
        model=model,
        key_points=key_points,
        profile=profile,
        stats=stats,
        models=models,
    )

    doc = Document()
    for section in doc.sections:
        section.top_margin    = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin   = Inches(1.2)
        section.right_margin  = Inches(1.2)

    def add_heading(text, size=14, color=(0x1a, 0x73, 0xe8)):
        p = doc.add_paragraph()
        r = p.add_run(text)
        r.bold = True
        r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(*color)

    def add_body(text):
        for line in text.split("\n"):
            line = line.strip()
            if line:
                p = doc.add_paragraph(line)
                p.runs[0].font.size = Pt(10)
                p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    # Page de garde
    add_heading(title, size=22)
    add_heading(institution, size=12, color=(0x5f, 0x63, 0x68))
    add_heading(f"Source : {filename} · {datetime.now().strftime('%d/%m/%Y')}", size=10, color=(0x5f, 0x63, 0x68))
    doc.add_page_break()

    # Sections
    for cle, sec_title in SECTIONS_RAPPORT:
        add_heading(sec_title)
        add_body(sections[cle])
        doc.add_paragraph()

    # Visualisations
    if images_b64:
        add_heading("Visualisations")
        for idx, img_b64 in enumerate(images_b64):
            try:
                buf = io.BytesIO(base64.b64decode(img_b64))
                doc.add_picture(buf, width=Inches(5.5))
                cap = doc.add_paragraph(f"Figure {idx + 1}")
                cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                cap.runs[0].font.size = Pt(9)
            except Exception:
                pass

    # Pied
    doc.add_paragraph()
    p = doc.add_paragraph("Rapport généré par No-Code Data Intelligence · CITADEL Ouagadougou")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.runs[0].font.size = Pt(8)
    p.runs[0].font.color.rgb = RGBColor(0x5f, 0x63, 0x68)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()


# ── Génération PowerPoint ───────────────────────────────────────
PPTX_PRIMAIRE = PptxRGB(0x1a, 0x73, 0xe8)
PPTX_ENCRE = PptxRGB(0x20, 0x21, 0x24)
PPTX_GRIS = PptxRGB(0x5f, 0x63, 0x68)

# Au-delà, le texte déborde de la zone de contenu et PowerPoint le rogne
# silencieusement à l'affichage. La section est alors répartie sur plusieurs
# diapositives plutôt que tronquée.
MAX_CAR_DIAPO = 700


def _paquets_de_texte(texte: str, maximum: int = MAX_CAR_DIAPO) -> list[str]:
    """Découpe une section en blocs tenant sur une diapositive.

    La coupe suit les paragraphes, et à défaut les phrases : couper au milieu
    d'une phrase donnerait une diapositive qui commence par une subordonnée
    orpheline. Un paragraphe unique plus long que la limite est donc scindé sur
    ses points, pas sur son compte de caractères.
    """
    paragraphes = [p.strip() for p in (texte or "").split("\n") if p.strip()]
    if not paragraphes:
        return [""]

    morceaux: list[str] = []
    for paragraphe in paragraphes:
        if len(paragraphe) <= maximum:
            morceaux.append(paragraphe)
            continue
        courant = ""
        for phrase in re.split(r"(?<=[.!?])\s+", paragraphe):
            if courant and len(courant) + len(phrase) + 1 > maximum:
                morceaux.append(courant)
                courant = phrase
            else:
                courant = f"{courant} {phrase}".strip()
        if courant:
            morceaux.append(courant)

    paquets: list[str] = []
    courant = ""
    for morceau in morceaux:
        if courant and len(courant) + len(morceau) + 1 > maximum:
            paquets.append(courant)
            courant = morceau
        else:
            courant = f"{courant}\n{morceau}".strip()
    if courant:
        paquets.append(courant)
    return paquets or [""]


def build_powerpoint_report(
    title: str,
    institution: str,
    filename: str,
    analysis_text: str,
    messages: list,
    images_b64: list,
    model: str | None = None,
    key_points: str = "",
    profile: dict | None = None,
    stats: dict | None = None,
    models: list | None = None,
) -> bytes:
    sections = draft_report_with_llm(
        filename=filename,
        analysis_text=analysis_text,
        chat_history=messages,
        title=title,
        institution=institution,
        model=model,
        key_points=key_points,
        profile=profile,
        stats=stats,
        models=models,
    )

    presentation = Presentation()
    # 16:9 — le 4:3 par défaut de python-pptx est un format d'écran que plus
    # personne ne projette, et il rogne la largeur utile des graphiques.
    presentation.slide_width = PptxInches(13.333)
    presentation.slide_height = PptxInches(7.5)
    largeur = presentation.slide_width
    hauteur = presentation.slide_height

    vierge = presentation.slide_layouts[6]
    marge = PptxInches(0.9)
    largeur_utile = largeur - 2 * marge

    def zone_texte(diapo, haut, hauteur_zone):
        cadre = diapo.shapes.add_textbox(marge, haut, largeur_utile, hauteur_zone).text_frame
        cadre.word_wrap = True
        return cadre

    def style(paragraphe, taille, couleur, gras=False, alignement=PP_ALIGN.LEFT):
        paragraphe.alignment = alignement
        for run in paragraphe.runs:
            run.font.size = PptxPt(taille)
            run.font.color.rgb = couleur
            run.font.bold = gras
            run.font.name = "Calibri"

    def diapo_titre_section(titre: str, corps: str, suite: bool = False):
        """Une diapositive de section : bandeau de titre, filet, puis le texte."""
        diapo = presentation.slides.add_slide(vierge)

        cadre_titre = zone_texte(diapo, PptxInches(0.55), PptxInches(0.9))
        paragraphe = cadre_titre.paragraphs[0]
        paragraphe.text = f"{titre} (suite)" if suite else titre
        style(paragraphe, 28, PPTX_PRIMAIRE, gras=True)

        filet = diapo.shapes.add_shape(MSO_SHAPE.RECTANGLE,marge, PptxInches(1.45), largeur_utile, Emu(12700))
        filet.fill.solid()
        filet.fill.fore_color.rgb = PPTX_PRIMAIRE
        filet.line.fill.background()
        filet.shadow.inherit = False

        cadre = zone_texte(diapo, PptxInches(1.85), hauteur - PptxInches(2.6))
        premier = True
        for ligne in corps.split("\n"):
            ligne = ligne.strip()
            if not ligne:
                continue
            paragraphe = cadre.paragraphs[0] if premier else cadre.add_paragraph()
            paragraphe.text = ligne
            style(paragraphe, 15, PPTX_ENCRE)
            paragraphe.space_after = PptxPt(10)
            premier = False
        return diapo

    # ── Diapositive de titre ───────────────────────────────────
    couverture = presentation.slides.add_slide(vierge)
    bandeau = couverture.shapes.add_shape(MSO_SHAPE.RECTANGLE,0, PptxInches(2.55), largeur, PptxInches(0.06))
    bandeau.fill.solid()
    bandeau.fill.fore_color.rgb = PPTX_PRIMAIRE
    bandeau.line.fill.background()
    bandeau.shadow.inherit = False

    cadre = zone_texte(couverture, PptxInches(2.75), PptxInches(2.2))
    paragraphe = cadre.paragraphs[0]
    paragraphe.text = title
    style(paragraphe, 40, PPTX_ENCRE, gras=True)
    for texte in (
        institution,
        f"Source analysée : {filename}",
        f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
    ):
        paragraphe = cadre.add_paragraph()
        paragraphe.text = texte
        style(paragraphe, 15, PPTX_GRIS)
        paragraphe.space_before = PptxPt(6)

    # ── Une à plusieurs diapositives par section ───────────────
    for cle, titre_section in SECTIONS_RAPPORT:
        for index, paquet in enumerate(_paquets_de_texte(sections[cle])):
            diapo_titre_section(titre_section, paquet, suite=index > 0)

    # ── Une diapositive par visualisation ──────────────────────
    haut_image = PptxInches(1.85)
    hauteur_max = hauteur - PptxInches(2.7)
    for index, img_b64 in enumerate(images_b64 or []):
        try:
            donnees = io.BytesIO(base64.b64decode(img_b64))
        except Exception:
            logger.warning("Visualisation %s illisible, diapositive ignorée.", index + 1)
            continue
        try:
            diapo = diapo_titre_section("Visualisations", "")
            image = diapo.shapes.add_picture(donnees, marge, haut_image, width=largeur_utile)
            # Ajouté à la largeur utile, le PNG garde son ratio : seule sa
            # hauteur peut déborder. On la ramène sous le plafond en
            # recalculant la largeur, plutôt qu'en imposant un cadre fixe qui
            # déformerait le graphique.
            if image.height > hauteur_max:
                ratio = image.width / image.height
                image.height = int(hauteur_max)
                image.width = int(hauteur_max * ratio)
            image.left = int((largeur - image.width) / 2)

            legende = diapo.shapes.add_textbox(
                marge, haut_image + image.height + PptxInches(0.1),
                largeur_utile, PptxInches(0.35),
            ).text_frame
            legende.word_wrap = True
            paragraphe = legende.paragraphs[0]
            paragraphe.text = f"Figure {index + 1}"
            style(paragraphe, 11, PPTX_GRIS, alignement=PP_ALIGN.CENTER)
        except Exception as exc:
            logger.warning("Visualisation %s non insérée : %s", index + 1, exc)

    # ── Diapositive de clôture ─────────────────────────────────
    fin = presentation.slides.add_slide(vierge)
    cadre = zone_texte(fin, hauteur // 2 - PptxInches(0.4), PptxInches(0.8))
    paragraphe = cadre.paragraphs[0]
    paragraphe.text = "Rapport généré par No-Code Data Intelligence · CITADEL Ouagadougou"
    style(paragraphe, 13, PPTX_GRIS, alignement=PP_ALIGN.CENTER)

    buffer = io.BytesIO()
    presentation.save(buffer)
    buffer.seek(0)
    return buffer.read()
