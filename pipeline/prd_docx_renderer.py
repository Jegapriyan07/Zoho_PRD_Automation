"""Render the generated PRD into the supplied project's editable Word layout."""
from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = "20365C"
ORANGE = "C96642"
PALE_BLUE = "DCE6F1"


def _document_metadata(markdown: str) -> tuple[str, str]:
    title = next((line[2:].strip() for line in markdown.splitlines() if line.startswith("# ")), "Client Project Requirements Document")
    subtitle = next(
        (line.strip().lstrip("> ") for line in markdown.splitlines()
         if line.strip() and not line.startswith("#") and not line.startswith("|") and not line.startswith(("- ", "* "))),
        "Requirements, validation findings, and delivery scope",
    )
    return title, subtitle


def _toc_entries(markdown: str) -> list[str]:
    return [line[3:].strip() for line in markdown.splitlines() if line.startswith("## ")]


def _shade(cell, color: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color)
    properties.append(shading)


def _set_cell_text(cell, text: str, bold: bool = False, color: str | None = None) -> None:
    cell.text = ""
    run = cell.paragraphs[0].add_run(text.strip())
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    run.font.size = Pt(10)


def _add_table(document: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    table = document.add_table(rows=1, cols=len(rows[0]))
    table.style = "Table Grid"
    for index, value in enumerate(rows[0]):
        _set_cell_text(table.rows[0].cells[index], value, bold=True, color="FFFFFF")
        _shade(table.rows[0].cells[index], NAVY)
    for values in rows[1:]:
        cells = table.add_row().cells
        for index, value in enumerate(values):
            _set_cell_text(cells[index], value)


def _add_paragraph(document: Document, text: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(8)
    for fragment in re.split(r"(\*\*.*?\*\*)", text):
        run = paragraph.add_run(fragment.replace("**", ""))
        run.bold = fragment.startswith("**")
        run.font.size = Pt(10.5)


def _add_markdown_body(document: Document, markdown: str) -> None:
    lines = markdown.splitlines()
    table_lines: list[str] = []
    for line in lines + [""]:
        if line.strip().startswith("|"):
            table_lines.append(line)
            continue
        if table_lines:
            rows = [
                [cell.strip() for cell in row.strip().strip("|").split("|")]
                for row in table_lines
                if not re.match(r"^\|[\s|:-]+\|$", row.strip())
            ]
            _add_table(document, rows)
            table_lines = []
        text = line.strip()
        if not text or text.startswith("# "):
            continue
        if text.startswith("## "):
            heading = document.add_heading(text[3:], level=1)
            heading.style = document.styles["Heading 1"]
            continue
        if text.startswith("### "):
            document.add_heading(text[4:], level=2)
            continue
        if text.startswith(("- ", "* ")):
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.add_run(text[2:]).font.size = Pt(10.5)
            continue
        _add_paragraph(document, text)


def render(markdown: str, output_path: Path) -> Path:
    """Create an editable DOCX reflecting the supplied PRD's visual structure."""
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)

    styles = document.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(10.5)
    styles["Heading 1"].font.name = "Aptos Display"
    styles["Heading 1"].font.size = Pt(18)
    styles["Heading 1"].font.bold = True
    styles["Heading 1"].font.color.rgb = RGBColor.from_string(ORANGE)
    styles["Heading 2"].font.name = "Aptos Display"
    styles["Heading 2"].font.size = Pt(13)
    styles["Heading 2"].font.bold = True
    styles["Heading 2"].font.color.rgb = RGBColor.from_string(NAVY)

    title_text, subtitle_text = _document_metadata(markdown)
    cover = document.add_paragraph()
    cover.paragraph_format.space_before = Inches(1.2)
    label = cover.add_run("PROJECT WORKFLOW DOCUMENT")
    label.bold = True
    label.font.size = Pt(11)
    label.font.color.rgb = RGBColor.from_string("666666")
    title_paragraph = document.add_paragraph()
    title_paragraph.paragraph_format.space_before = Inches(0.35)
    title_run = title_paragraph.add_run(title_text)
    title_run.bold = True
    title_run.font.name = "Aptos Display"
    title_run.font.size = Pt(30)
    title_run.font.color.rgb = RGBColor.from_string(NAVY)
    subtitle = document.add_paragraph(subtitle_text)
    subtitle.runs[0].font.size = Pt(16)
    subtitle.runs[0].font.color.rgb = RGBColor.from_string(ORANGE)
    document.add_paragraph("Prepared for: [Editable client name]\nVersion: 1\nDate: [Editable date]\nPlatform: Zoho Analytics")
    document.add_page_break()

    document.add_heading("Table of Contents", level=1)
    for index, entry in enumerate(_toc_entries(markdown), start=1):
        document.add_paragraph(f"{index}. {entry}")
    document.add_page_break()

    _add_markdown_body(document, markdown)
    footer = document.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("Zoho Analytics | Client Project Requirements Document")
    footer.runs[0].font.color.rgb = RGBColor.from_string("777777")
    document.save(output_path)
    return output_path


def render_pdf(markdown: str, output_path: Path) -> Path:
    """Create a PDF using the same PRD structure and color palette as the DOCX."""
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "PrdBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5,
        leading=13, spaceAfter=7,
    )
    heading = ParagraphStyle(
        "PrdHeading", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=16, leading=20, textColor=colors.HexColor(f"#{ORANGE}"),
        spaceBefore=12, spaceAfter=8,
    )
    subheading = ParagraphStyle(
        "PrdSubheading", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=12, leading=15, textColor=colors.HexColor(f"#{NAVY}"),
        spaceBefore=8, spaceAfter=5,
    )
    cover_label = ParagraphStyle(
        "CoverLabel", parent=body, alignment=TA_CENTER, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#666666"), fontSize=10,
    )
    cover_title = ParagraphStyle(
        "CoverTitle", parent=body, alignment=TA_CENTER, fontName="Helvetica-Bold",
        textColor=colors.HexColor(f"#{NAVY}"), fontSize=24, leading=29, spaceBefore=12,
    )
    cover_subtitle = ParagraphStyle(
        "CoverSubtitle", parent=body, alignment=TA_CENTER,
        textColor=colors.HexColor(f"#{ORANGE}"), fontSize=13, leading=16,
    )
    title_text, subtitle_text = _document_metadata(markdown)
    story = [
        Spacer(1, 1.0 * inch),
        Paragraph("PROJECT WORKFLOW DOCUMENT", cover_label),
        Paragraph(escape(title_text), cover_title),
        Paragraph(escape(subtitle_text), cover_subtitle),
        Spacer(1, 0.25 * inch),
        Paragraph("Prepared for: [Editable client name]<br/>Version: 1<br/>Date: [Editable date]<br/>Platform: Zoho Analytics", cover_label),
        Spacer(1, 0.8 * inch),
        Paragraph("Table of Contents", heading),
        *[Paragraph(f"{index}. {escape(entry)}", body) for index, entry in enumerate(_toc_entries(markdown), start=1)],
        Spacer(1, 0.25 * inch),
    ]

    def add_table(table_lines: list[str]) -> None:
        rows = [
            [cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in table_lines
            if not re.match(r"^\|[\s|:-]+\|$", line.strip())
        ]
        if not rows:
            return
        available_width = A4[0] - 1.0 * inch
        widths = [available_width / len(rows[0])] * len(rows[0])
        table_data = [[Paragraph(escape(value), body) for value in row] for row in rows]
        table_data[0] = [Paragraph(value.replace("&", "&amp;"), ParagraphStyle(
            "TableHeader", parent=body, fontName="Helvetica-Bold", textColor=colors.white,
        )) for value in rows[0]]
        table = Table(table_data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{NAVY}")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#A6A6A6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.12 * inch))

    table_lines: list[str] = []
    for line in markdown.splitlines() + [""]:
        if line.strip().startswith("|"):
            table_lines.append(line)
            continue
        if table_lines:
            add_table(table_lines)
            table_lines = []
        text = line.strip()
        if not text or text.startswith("# "):
            continue
        if text.startswith("## "):
            story.append(Paragraph(text[3:], heading))
        elif text.startswith("### "):
            story.append(Paragraph(text[4:], subheading))
        elif text.startswith(("- ", "* ")):
            story.append(Paragraph("• " + text[2:], body))
        else:
            story.append(Paragraph(escape(text), body))

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawCentredString(A4[0] / 2, 0.42 * inch, "Zoho Analytics | Client Project Requirements Document")
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(output_path), pagesize=A4, rightMargin=0.5 * inch, leftMargin=0.5 * inch,
        topMargin=0.55 * inch, bottomMargin=0.65 * inch,
        title="Client Project Requirements Document",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output_path