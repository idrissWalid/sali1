import io
import base64
from datetime import datetime
from app.services.gemini_service import complete_text
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

PRIMARY = HexColor("#1a73e8")
# ── Rédaction du rapport par Gemini ────────────────────────────
def draft_report_with_llm(
    filename: str,
    analysis_text: str,
    chat_history: list,
    title: str,
    institution: str,
    model: str = "gemma2:latest"
) -> dict:
    """
    Demande à Gemini de rédiger un rapport structuré
    à partir des éléments de la session.
    Retourne un dict avec les sections du rapport.
    """
    history_summary = "\n".join([
        f"[{m['role'].upper()}] {m['text'][:500]}"
        for m in chat_history
    ])

    prompt = f"""
Tu es un expert en rédaction de rapports analytiques institutionnels.

Voici les éléments d'une session d'analyse de données :

FICHIER ANALYSÉ : {filename}
TITRE DU RAPPORT : {title}
INSTITUTION : {institution}

ANALYSE INITIALE :
{analysis_text}

ÉCHANGES DE LA SESSION :
{history_summary}

Rédige un rapport analytique complet, structuré et professionnel.
Le rapport doit être directement publiable dans un contexte institutionnel.

Retourne EXACTEMENT ce format JSON (sans markdown) :
{{
  "resume_executif": "3 à 5 phrases résumant les conclusions principales",
  "description_donnees": "Description complète du jeu de données : variables, dimensions, qualité, période couverte",
  "resultats": "Section principale des résultats analytiques, bien structurée en paragraphes. Minimum 200 mots.",
  "conclusions": "Conclusions clés et implications pratiques pour l'institution",
  "recommandations": "3 à 5 recommandations concrètes et actionnables numérotées"
}}
"""
    try:
        text = complete_text(prompt, model).strip()

        # Nettoyer les backticks si présents
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        import json
        return json.loads(text)
    except Exception:
        # Fallback si JSON mal formé
        return {
            "resume_executif": analysis_text[:300],
            "description_donnees": analysis_text,
            "resultats": history_summary,
            "conclusions": "Voir les échanges de la session.",
            "recommandations": "1. Approfondir l'analyse avec un dataset plus large.",
        }


# ── Génération PDF ──────────────────────────────────────────────
def build_pdf_report(
    title: str,
    institution: str,
    filename: str,
    analysis_text: str,
    messages: list,
    images_b64: list,
) -> bytes:
    sections = draft_report_with_llm(
        filename=filename,
        analysis_text=analysis_text,
        chat_history=messages,
        title=title,
        institution=institution,
        model=messages[-1].get("model", "gemma2:latest") if messages else "gemma2:latest"
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
) -> bytes:
    sections = draft_report_with_llm(
        filename=filename,
        analysis_text=analysis_text,
        chat_history=messages,
        title=title,
        institution=institution,
        model=messages[-1].get("model", "gemma2:latest") if messages else "gemma2:latest"
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
    sections_content = [
        ("Résumé exécutif", sections["resume_executif"]),
        ("Description du jeu de données", sections["description_donnees"]),
        ("Résultats analytiques", sections["resultats"]),
        ("Conclusions", sections["conclusions"]),
        ("Recommandations", sections["recommandations"]),
    ]

    for sec_title, sec_content in sections_content:
        add_heading(sec_title)
        add_body(sec_content)
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
