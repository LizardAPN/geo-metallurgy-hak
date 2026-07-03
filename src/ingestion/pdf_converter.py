import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .utils import normalize_text

_DEFAULT_URL = "http://localhost:28080"
_DEFAULT_BATCH = 5
_DEFAULT_WORKERS = 3

# One shared pool for the whole process — limits total concurrent Docling requests
_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=_max_workers())
    return _pool


def _docling_url() -> str:
    return os.environ.get("DOCLING_URL", _DEFAULT_URL).rstrip("/")


def _batch_size() -> int:
    return int(os.environ.get("DOCLING_PAGES_PER_BATCH", _DEFAULT_BATCH))


def _max_workers() -> int:
    return int(os.environ.get("DOCLING_WORKERS", _DEFAULT_WORKERS))




def _page_count(src: Path) -> int:
    try:
        import fitz
        doc = fitz.open(str(src))
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return 0


def _extract_page_bytes(src: Path, page_num: int) -> bytes:
    """Extract a single page from PDF as a standalone PDF in memory."""
    import fitz
    src_doc = fitz.open(str(src))
    page_doc = fitz.open()
    page_doc.insert_pdf(src_doc, from_page=page_num, to_page=page_num)
    data = page_doc.tobytes()
    page_doc.close()
    src_doc.close()
    return data


def _call_docling_page(page_bytes: bytes, name: str) -> str:
    import requests

    url = f"{_docling_url()}/v1/convert/file"
    files = [("files", (name, page_bytes, "application/pdf"))]
    data = [
        ("to_formats", "md"),
        ("ocr_engine", "tesseract"),
        ("ocr_lang", "rus"),
        ("ocr_lang", "eng"),
        ("do_ocr", "true"),
        ("do_table_structure", "true"),
        ("include_images", "false"),
        ("image_export_mode", "placeholder"),
    ]
    resp = requests.post(url, files=files, data=data, timeout=300)

    if resp.status_code != 200:
        raise RuntimeError(f"Docling HTTP {resp.status_code}: {resp.text[:300]}")

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


def _build_page_map(md: str, batch_markers: list[tuple[int, int, int]]) -> list[dict]:
    """
    batch_markers: list of (start_page, end_page, md_line_offset)
    Returns page_map blocks — one per page batch.
    """
    page_map = []
    lines = md.splitlines()

    for idx, (start_page, end_page, line_offset) in enumerate(batch_markers):
        # find next marker to know where this batch ends
        if idx + 1 < len(batch_markers):
            next_offset = batch_markers[idx + 1][2]
        else:
            next_offset = len(lines)

        # find actual first/last non-empty line in this batch's range
        batch_lines = lines[line_offset:next_offset]
        nonempty = [i for i, l in enumerate(batch_lines) if l.strip()]
        if nonempty:
            md_start = line_offset + nonempty[0] + 1   # 1-indexed
            md_end   = line_offset + nonempty[-1] + 1
        else:
            md_start = md_end = line_offset + 1

        for page in range(start_page, end_page + 1):
            page_map.append({
                "block_id": f"block_{page:03d}",
                "page": page,
                "type": "text",
                "md_start_line": md_start,
                "md_end_line": md_end,
            })

    return page_map


def _print_progress(name: str, done: int, total: int) -> None:
    bar_width = 30
    filled = int(bar_width * done / total) if total else bar_width
    bar = "█" * filled + "░" * (bar_width - filled)
    pct = int(100 * done / total) if total else 100
    print(f"\r    [{bar}] {pct:3d}%  {done}/{total} стр  {name}", end="", flush=True)


def convert_pdf(src: Path, out_dir: Path) -> tuple[str, list[dict], list[str], str]:
    """
    Convert PDF via Docling API — one request per page, pages run in parallel.
    Returns (parse_method, page_map, warnings, markdown_text).
    """
    warnings: list[str] = []
    total_pages = _page_count(src)
    if total_pages == 0:
        return "docling_ocr", [], ["Could not determine page count"], ""

    name = src.name[:40]
    _print_progress(name, 0, total_pages)

    results: dict[int, str] = {}
    errors: list[str] = []
    done_count = 0

    workers = _max_workers()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_call_docling_page, _extract_page_bytes(src, p), f"p{p+1}_{src.name}"): p
            for p in range(total_pages)
        }
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                results[page_num] = future.result()
            except Exception as e:
                errors.append(f"page {page_num + 1}: {e}")
            done_count += 1
            _print_progress(name, done_count, total_pages)

    print()

    if errors:
        warnings.extend(errors)

    # Reassemble in order
    parts: list[str] = []
    batch_markers: list[tuple[int, int, int]] = []
    current_line = 0

    for p in range(total_pages):
        md_part = results.get(p, "")
        if not md_part.strip():
            continue
        normalized = normalize_text(md_part)
        batch_markers.append((p + 1, p + 1, current_line))
        parts.append(normalized)
        current_line += len(normalized.splitlines()) + 1

    if not parts:
        warnings.append("No text extracted from PDF via Docling")
        return "docling_ocr", [], warnings, ""

    markdown = "\n\n".join(parts)
    page_map = _build_page_map(markdown, batch_markers)
    parse_method = "docling_ocr_partial" if errors else "docling_ocr"

    return parse_method, page_map, warnings, markdown
