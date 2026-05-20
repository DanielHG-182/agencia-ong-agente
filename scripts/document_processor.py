"""
document_processor.py
Handles conversion of PDF, DOCX, and TXT files to clean Markdown.
"""

import re
from pathlib import Path


# ─────────────────────────────────────────────────────────
# TEXT UTILITIES
# ─────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Normalize whitespace and remove garbage characters."""
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\x00', '', text)
    return text.strip()


def wrap_table(rows: list[list[str]], source: str) -> str:
    """
    Converts a 2D list into a fenced Markdown table.
    Tables are wrapped in HTML comments so the LLM knows
    this is source data — not to be rewritten or inferred.
    """
    if not rows or not rows[0]:
        return ""

    header    = "| " + " | ".join(str(c).strip() for c in rows[0]) + " |"
    separator = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body      = [
        "| " + " | ".join(str(c or "").strip().replace("\n", " ") for c in row) + " |"
        for row in rows[1:]
    ]

    lines = [
        f"\n<!-- TABLE: {source} -->",
        header,
        separator,
        *body,
        "<!-- END TABLE -->\n"
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# TXT
# ─────────────────────────────────────────────────────────

def convert_txt(path: Path) -> str:
    """
    Reads plain text and applies a simple heuristic:
    short ALL-CAPS lines are treated as section headings.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="latin-1")

    lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.isupper() and 5 < len(stripped) < 80:
            lines.append(f"\n## {stripped.title()}\n")
        else:
            lines.append(line)

    return clean_text("\n".join(lines))


# ─────────────────────────────────────────────────────────
# DOCX
# ─────────────────────────────────────────────────────────

HEADING_MAP = {
    "Heading 1": "#",
    "Heading 2": "##",
    "Heading 3": "###",
    "Heading 4": "####",
    "Title":     "#",
    "Subtitle":  "##",
}

def convert_docx(path: Path) -> str:
    """
    Walks the document body in order (paragraphs + tables)
    to preserve the original structure.
    Heading styles map to Markdown #.
    Bold-only short paragraphs are treated as implicit headings.
    """
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc   = Document(path)
    lines = []

    for element in doc.element.body:
        tag = element.tag.split("}")[-1]

        if tag == "p":
            para  = Paragraph(element, doc)
            text  = para.text.strip()
            if not text:
                lines.append("")
                continue

            style  = para.style.name if para.style else ""
            prefix = HEADING_MAP.get(style)

            if prefix:
                lines.append(f"\n{prefix} {text}\n")
            elif (
                len(text) < 100
                and all(r.bold for r in para.runs if r.text.strip())
                and para.runs
            ):
                lines.append(f"\n### {text}\n")
            else:
                lines.append(text)

        elif tag == "tbl":
            table = Table(element, doc)
            rows  = [
                [cell.text.strip() for cell in row.cells]
                for row in table.rows
            ]
            lines.append(wrap_table(rows, source=path.name))

    return clean_text("\n".join(lines))


# ─────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────

def convert_pdf(path: Path) -> str:
    """
    Two-pass extraction:
      1. pdfplumber  → tables (structure-aware)
      2. pymupdf     → text blocks (layout-aware)
    Tables found by pdfplumber are injected after their page text.
    """
    import fitz
    import pdfplumber

    # Pass 1 — extract tables per page
    tables_by_page: dict[int, list] = {}
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            if tables:
                tables_by_page[i] = tables

    # Pass 2 — extract text blocks
    doc    = fitz.open(path)
    output = []

    for page_num in range(len(doc)):
        page   = doc[page_num]
        blocks = page.get_text("blocks", sort=True)
        lines  = [f"\n<!-- PAGE {page_num + 1} -->"]

        for block in blocks:
            if block[6] != 0:       # skip non-text blocks
                continue
            text = block[4].strip()
            if not text:
                continue

            single_line = text.replace("\n", " ").strip()

            # Heuristic: short lines starting with uppercase → heading
            if len(single_line) < 80 and single_line[0].isupper() and len(single_line.split()) <= 8:
                lines.append(f"\n## {single_line}\n")
            else:
                lines.append(single_line)

        # Inject tables for this page
        for i, table in enumerate(tables_by_page.get(page_num, [])):
            source = f"{path.name} — p.{page_num + 1} table {i + 1}"
            lines.append(wrap_table(table, source=source))

        output.append("\n".join(lines))

    doc.close()
    return clean_text("\n\n".join(output))


# ─────────────────────────────────────────────────────────
# PUBLIC INTERFACE
# ─────────────────────────────────────────────────────────

CONVERTERS = {
    ".txt":  convert_txt,
    ".docx": convert_docx,
    ".doc":  convert_docx,
    ".pdf":  convert_pdf,
}

def process_document(path: Path) -> str | None:
    """
    Entry point. Receives a file path, returns clean Markdown string.
    Returns None if the extension is not supported.
    """
    ext = path.suffix.lower()
    converter = CONVERTERS.get(ext)

    if not converter:
        return None

    return converter(path)