#!/usr/bin/env python3
"""
Document Normalization Layer — entry point.

Usage:
    python scripts/process_incoming.py [--only-docx|--only-pdf] [--source PATH]

  --only-docx     Process only DOCX files (no Docling server required).
  --only-pdf      Process only PDF files (requires Docling).
  --source PATH   Override source directory (default: data/corpus/).
                  Scanned recursively for .pdf / .docx / .pptx.

Requires DOCLING_URL in .env (or environment) for PDF/PPTX.
Results go to data/processed/{doc_id}/.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# load .env
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from src.ingestion.dispatcher import dispatch
from src.ingestion.utils import ensure_dirs

CORPUS   = Path("data/corpus")
PROCESSED = Path("data/processed")
FAILED   = Path("data/failed")
ARCHIVE  = Path("data/archive")


def main():
    args = sys.argv[1:]
    only_docx = "--only-docx" in args
    only_pdf  = "--only-pdf"  in args

    source_dir = CORPUS
    if "--source" in args:
        idx = args.index("--source")
        source_dir = Path(args[idx + 1])

    ensure_dirs(PROCESSED, FAILED, ARCHIVE)

    if only_docx:
        allowed = {".docx"}
        print("Mode: DOCX only (PDF/PPTX skipped)\n")
    elif only_pdf:
        allowed = {".pdf"}
        docling_url = os.environ.get("DOCLING_URL", "http://localhost:28080")
        print(f"Mode: PDF only  |  Docling: {docling_url}\n")
    else:
        allowed = {".pdf", ".docx", ".pptx"}
        docling_url = os.environ.get("DOCLING_URL", "http://localhost:28080")
        print(f"Mode: all formats  |  Docling: {docling_url}\n")

    if not source_dir.exists():
        print(f"ERROR: source directory not found: {source_dir}", file=sys.stderr)
        sys.exit(1)

    files = sorted(
        f for f in source_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in allowed
    )

    total = len(files)
    success = 0
    duplicates = 0
    failed = 0
    skipped = 0

    print(f"Source : {source_dir}")
    print(f"Found  : {total} file(s)\n")

    for f in files:
        rel = f.relative_to(source_dir)
        print(f"  [{rel}]")
        result = dispatch(f)
        outcome = result.get("outcome", "unknown")

        if outcome == "duplicate":
            print(f"    → already processed ({result.get('doc_id')})")
            duplicates += 1
        elif outcome in ("success", "warning"):
            tag = " [warnings]" if outcome == "warning" else ""
            print(f"    → OK{tag}  {result.get('doc_id')}")
            success += 1
        elif outcome == "skipped":
            print(f"    → skipped ({result.get('reason')})")
            skipped += 1
        elif outcome == "failed":
            print(f"    → FAILED: {result.get('error', 'see parse_log.json')}")
            failed += 1

    print(f"""
Summary
-------
Total    : {total}
Success  : {success}
Duplicate: {duplicates}
Failed   : {failed}
Skipped  : {skipped}
""")


if __name__ == "__main__":
    main()
