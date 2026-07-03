import shutil
from pathlib import Path

from .docx_converter import convert_docx
from .metadata import build_metadata, build_parse_log
from .pdf_converter import convert_pdf
from .pptx_converter import convert_pptx
from .utils import (
    compute_file_hash,
    make_doc_id,
    write_json,
)

SUPPORTED_EXTENSIONS = ("pdf", "docx", "pptx")
PROCESSED_DIR = Path("data/processed")
FAILED_DIR = Path("data/failed")


def _already_processed(doc_id: str) -> bool:
    out = PROCESSED_DIR / doc_id
    return out.exists() and (out / "metadata.json").exists()


def _map_filename(ext: str) -> str:
    return {"pdf": "page_map.json", "pptx": "slide_map.json"}.get(ext, "structure_map.json")


def dispatch(src: Path) -> dict:
    """
    Process a single PDF, DOCX, or PPTX file.
    Source file is NOT copied — absolute path is stored in metadata.json.
    Returns a summary dict with doc_id and outcome.
    """
    ext = src.suffix.lower().lstrip(".")
    if ext not in SUPPORTED_EXTENSIONS:
        return {"file": src.name, "outcome": "skipped", "reason": "unsupported extension"}

    file_hash = compute_file_hash(src)
    doc_id = make_doc_id(file_hash)

    if _already_processed(doc_id):
        return {"file": src.name, "doc_id": doc_id, "outcome": "duplicate"}

    out_dir = PROCESSED_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []

    steps.append({"step": "detect_file_type", "status": "success"})

    parse_method = "unknown"
    map_data = []
    markdown = ""
    doc_meta = None

    try:
        if ext == "pdf":
            parse_method, map_data, conv_warnings, markdown = convert_pdf(src, out_dir)
        elif ext == "docx":
            parse_method, map_data, conv_warnings, markdown, doc_meta = convert_docx(src, out_dir)
        else:
            parse_method, map_data, conv_warnings, markdown = convert_pptx(src, out_dir)

        warnings.extend(conv_warnings)
        step_status = "warning" if conv_warnings else "success"
        steps.append({"step": "convert_to_markdown", "status": step_status})
    except Exception as exc:
        errors.append(str(exc))
        steps.append({"step": "convert_to_markdown", "status": "failed"})
        _move_to_failed(src, doc_id, out_dir, steps, warnings, errors)
        return {"file": src.name, "doc_id": doc_id, "outcome": "failed", "error": str(exc)}

    try:
        (out_dir / "document.md").write_text(markdown, encoding="utf-8")
        write_json(out_dir / _map_filename(ext), map_data)

        meta = build_metadata(
            doc_id=doc_id,
            file_name=src.name,
            file_type=ext,
            file_hash=file_hash,
            file_size_bytes=src.stat().st_size,
            parse_method=parse_method,
            status="success" if not errors else "failed",
            out_dir=out_dir,
            original_path=src,
            doc_meta=doc_meta,
        )
        write_json(out_dir / "metadata.json", meta)
        steps.append({"step": "save_metadata", "status": "success"})
    except Exception as exc:
        errors.append(str(exc))
        steps.append({"step": "save_metadata", "status": "failed"})

    parse_log = build_parse_log(doc_id, steps, warnings, errors)
    write_json(out_dir / "parse_log.json", parse_log)

    if errors:
        _move_to_failed(src, doc_id, out_dir, steps, warnings, errors)
        return {"file": src.name, "doc_id": doc_id, "outcome": "failed"}

    outcome = "warning" if warnings else "success"
    return {"file": src.name, "doc_id": doc_id, "outcome": outcome}


def _move_to_failed(src: Path, doc_id: str, out_dir: Path, steps, warnings, errors):
    fail_dir = FAILED_DIR / doc_id
    fail_dir.mkdir(parents=True, exist_ok=True)
    # store path reference instead of copying the file
    write_json(fail_dir / "source_path.json", {"source_path": str(src.resolve())})
    parse_log = build_parse_log(doc_id, steps, warnings, errors)
    write_json(fail_dir / "parse_log.json", parse_log)
    if out_dir.exists():
        shutil.rmtree(out_dir)
