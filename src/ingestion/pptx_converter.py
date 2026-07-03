import os
from pathlib import Path

from .utils import normalize_text

_DEFAULT_URL = "http://localhost:28080"


def _docling_url() -> str:
    return os.environ.get("DOCLING_URL", _DEFAULT_URL).rstrip("/")


def _call_docling(src: Path) -> str:
    import requests

    url = f"{_docling_url()}/v1/convert/file"
    with src.open("rb") as f:
        files = [("files", (src.name, f, "application/vnd.openxmlformats-officedocument.presentationml.presentation"))]
        data = [
            ("to_formats", "md"),
            ("do_table_structure", "true"),
            ("include_images", "false"),
            ("image_export_mode", "placeholder"),
        ]
        resp = requests.post(url, files=files, data=data, timeout=1800)

    if resp.status_code != 200:
        raise RuntimeError(
            f"Docling HTTP {resp.status_code}: {resp.text[:500]}"
        )

    result = resp.json()
    doc = result.get("document", result)
    if isinstance(doc, dict):
        for key in ("md_content", "markdown", "text", "content"):
            v = doc.get(key)
            if isinstance(v, str) and v.strip():
                return v
    for key in ("md_content", "markdown", "text", "content"):
        v = result.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _build_slide_map(md: str) -> list[dict]:
    """
    Docling outputs PPTX slides as sections. We derive slide_map from
    heading markers in the markdown (## Slide N or similar patterns).
    Falls back to one block for the whole document.
    """
    lines = md.splitlines()
    slide_map = []
    block_num = 0

    # detect slide breaks: lines that look like "## Slide N" or "# Slide N"
    # or Docling's own section markers
    import re
    slide_pat = re.compile(r'^#{1,3}\s*(slide|слайд)\s*\d+', re.IGNORECASE)

    current_start = 1
    current_slide = 1

    for i, line in enumerate(lines, start=1):
        if slide_pat.match(line) and i > 1:
            block_num += 1
            slide_map.append({
                "block_id": f"block_{block_num:03d}",
                "slide": current_slide,
                "type": "slide",
                "md_start_line": current_start,
                "md_end_line": i - 1,
            })
            current_slide += 1
            current_start = i

    # last (or only) block
    block_num += 1
    slide_map.append({
        "block_id": f"block_{block_num:03d}",
        "slide": current_slide,
        "type": "slide",
        "md_start_line": current_start,
        "md_end_line": len(lines),
    })

    return slide_map


def convert_pptx(src: Path, out_dir: Path) -> tuple[str, list[dict], list[str], str]:
    """
    Convert PPTX via Docling API.
    Returns (parse_method, slide_map, warnings, markdown_text).
    """
    warnings: list[str] = []

    try:
        raw = _call_docling(src)
    except Exception as e:
        raise RuntimeError(f"Docling PPTX conversion failed: {e}")

    if not raw.strip():
        warnings.append("No text extracted from PPTX via Docling")
        return "docling_pptx", [], warnings, ""

    markdown = normalize_text(raw)
    slide_map = _build_slide_map(markdown)

    return "docling_pptx", slide_map, warnings, markdown
