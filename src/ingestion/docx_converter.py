import re
from pathlib import Path

from .utils import normalize_text


def _is_bold_run(para) -> bool:
    """Return True if the paragraph's first non-empty run is bold."""
    for run in para.runs:
        if run.text.strip():
            return bool(run.bold)
    return False


def _is_pseudo_heading(para, text: str) -> int:
    """
    Detect paragraphs that are structurally headings but use bold formatting
    instead of Word Heading styles.  Returns heading level (1–4) or 0.

    Strict rules to avoid false positives:
      - text ≤ 80 chars
      - does NOT end with a period (prose sentences do)
      - does NOT look like a figure/table caption ("Рисунок N", "Таблица N")
      - does NOT look like a signature line (underscores, date placeholders)
      - does NOT look like a TOC entry (ends with a page number)
      - does NOT look like a doc code or code+date (e.g. "ОИП – 02 – 2025")
      - first non-empty run MUST be bold
      - text starts with a decimal section number OR is fully upper-case (≥ 5 chars)
    """
    if len(text) > 80:
        return 0
    if text.endswith("."):
        return 0
    # figure / table captions
    if re.match(r"^(Рисунок|Таблица|Рис\.|Табл\.)\s", text, re.IGNORECASE):
        return 0
    # signature / placeholder lines (underscores, slashes, date fragments)
    if re.search(r"_{3,}|_{2,}|\bг\.\b|\d{4}\s*г", text):
        return 0
    # TOC lines ending with a page number
    if re.search(r"\s{2,}|\d+\s*$", text) and re.search(r"\d$", text):
        return 0
    # doc codes like "ОИП – 02 – 2025"
    if re.fullmatch(r"[\w\d]+[\s–\-]+[\d]+[\s–\-].*\d{4}", text):
        return 0
    # lines that are mostly punctuation / numbers
    if re.fullmatch(r"[\d\s\-–—_/\\«»().,:;]+", text):
        return 0

    if not _is_bold_run(para):
        return 0

    is_upper = text.isupper() and len(text) >= 5

    # Must start with section number OR be all-caps
    if not (re.match(r"^\d", text) or is_upper):
        return 0

    # Guess level from numbering depth
    if re.match(r"^\d+\.\d+\.\d+", text):
        return 4
    if re.match(r"^\d+\.\d+", text):
        return 3
    if re.match(r"^\d+[\s.]", text):
        return 2
    return 2


def _extract_doc_meta(doc) -> dict:
    """Extract title, author, dates and hyperlinks from a DOCX document."""
    cp = doc.core_properties

    # Prefer explicit title; fall back to first heading in body
    title = (cp.title or "").strip()
    if not title:
        for para in doc.paragraphs:
            style = para.style.name if para.style else ""
            if _heading_level(style) == 1 and para.text.strip():
                title = para.text.strip()
                break

    # Hyperlinks from relationships
    hyperlinks = [
        rel.target_ref
        for rel in doc.part.rels.values()
        if "hyperlink" in rel.reltype and rel.target_ref
    ]

    return {
        "title": title or None,
        "author": (cp.author or "").strip() or None,
        "created": cp.created.isoformat() if cp.created else None,
        "modified": cp.modified.isoformat() if cp.modified else None,
        "hyperlinks": hyperlinks,
    }


def _table_to_md(table) -> list[str]:
    rows = []
    for i, row in enumerate(table.rows):
        cells = [cell.text.replace("|", "\\|").replace("\n", " ").strip() for cell in row.cells]
        rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            rows.append("|" + "|".join(["---"] * len(cells)) + "|")
    return rows


def _heading_level(style_name: str) -> int:
    name = style_name.lower().strip()
    for lvl in range(1, 7):
        if f"heading {lvl}" in name or f"заголовок {lvl}" in name:
            return lvl

    # Russian shorthand custom styles: "1ш", "2ш", "3ш" → heading 1/2/3
    m = re.match(r"^(\d)ш$", name)
    if m:
        return int(m.group(1))

    return 0


def convert_docx(src: Path, out_dir: Path) -> tuple[str, list[dict], list[str], str, dict]:
    """
    Returns (parse_method, structure_map, warnings, markdown_text, doc_meta).
    """
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")

    doc = Document(str(src))
    doc_meta = _extract_doc_meta(doc)
    warnings: list[str] = []
    structure_map: list[dict] = []
    md_lines: list[str] = []
    current_line = 1
    current_section = ""
    block_num = 0

    # iterate body children to preserve order of paragraphs and tables
    body = doc.element.body
    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            from docx.text.paragraph import Paragraph as DocxParagraph
            para = DocxParagraph(child, doc)
            text = para.text.strip()
            style = para.style.name if para.style else ""
            level = _heading_level(style)

            if not text:
                continue

            # Detect pseudo-headings formatted with bold instead of Heading styles
            pseudo = False
            if not level:
                level = _is_pseudo_heading(para, text)
                pseudo = bool(level)

            block_num += 1
            block_id = f"block_{block_num:03d}"
            start = current_line

            if level:
                prefix = "#" * level
                line = f"{prefix} {text}"
                md_lines.append(line)
                md_lines.append("")
                current_section = text
                entry = {
                    "block_id": block_id,
                    "type": "heading",
                    "level": level,
                    "text": text,
                    "md_start_line": start,
                    "md_end_line": start,
                }
                if pseudo:
                    entry["pseudo_heading"] = True
                structure_map.append(entry)
                current_line = start + 2
            else:
                normalized = normalize_text(text)
                lines = normalized.splitlines() or [normalized]
                md_lines.extend(lines)
                md_lines.append("")
                end = start + len(lines) - 1
                structure_map.append(
                    {
                        "block_id": block_id,
                        "type": "paragraph",
                        "section": current_section,
                        "md_start_line": start,
                        "md_end_line": end,
                    }
                )
                current_line = end + 2

        elif tag == "tbl":
            from docx.table import Table as DocxTable
            table = DocxTable(child, doc)
            block_num += 1
            block_id = f"block_{block_num:03d}"
            start = current_line
            table_lines = _table_to_md(table)
            md_lines.extend(table_lines)
            md_lines.append("")
            end = start + len(table_lines) - 1
            structure_map.append(
                {
                    "block_id": block_id,
                    "type": "table",
                    "section": current_section,
                    "md_start_line": start,
                    "md_end_line": end,
                }
            )
            current_line = end + 2

    if not md_lines:
        warnings.append("Document appears to be empty")

    markdown = "\n".join(md_lines)
    return "python_docx", structure_map, warnings, markdown, doc_meta
