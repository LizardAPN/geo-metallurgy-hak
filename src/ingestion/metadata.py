from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _rel_path(p: Path | None) -> str | None:
    if p is None:
        return None
    try:
        return str(p.resolve().relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(p.resolve())


def build_metadata(
    doc_id: str,
    file_name: str,
    file_type: str,
    file_hash: str,
    file_size_bytes: int,
    parse_method: str,
    status: str,
    out_dir: Path,
    original_path: Path | None = None,
    doc_meta: dict | None = None,
) -> dict:
    meta = {
        "doc_id": doc_id,
        "file_name": file_name,
        "file_type": file_type,
        "file_hash": file_hash,
        "file_size_bytes": file_size_bytes,
        "parse_method": parse_method,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": _rel_path(original_path),
        "document_md_path": _rel_path(out_dir / "document.md"),
    }
    # merge document-level fields (title, author, dates, hyperlinks) if provided
    if doc_meta:
        meta.update(doc_meta)
    return meta


def build_parse_log(doc_id: str, steps: list[dict], warnings: list[str], errors: list[str]) -> dict:
    if errors:
        status = "failed"
    elif warnings:
        status = "warning"
    else:
        status = "success"
    return {
        "doc_id": doc_id,
        "status": status,
        "steps": steps,
        "warnings": warnings,
        "errors": errors,
    }
