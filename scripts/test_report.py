#!/usr/bin/env python3
"""
Report quality of processed documents from a test sample.

Usage:
    python scripts/test_report.py [--source data/test_run]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.utils import compute_file_hash, make_doc_id

TEST_DIR  = Path("data/test_run")
PROCESSED = Path("data/processed")

if "--source" in sys.argv:
    TEST_DIR = Path(sys.argv[sys.argv.index("--source") + 1])

files = sorted(
    f for f in TEST_DIR.iterdir()
    if f.suffix.lower() in (".pdf", ".docx", ".pptx")
)

print(f"Test sample: {TEST_DIR}  ({len(files)} files)\n")
print(f"{'File':<52} {'Type':<5} {'Status':<9} {'Method':<22} {'Lines':>6} {'Blocks':>7}")
print("─" * 108)

total = 0
ok = 0
warn = 0
fail = 0
not_run = 0

for f in files:
    total += 1
    file_hash = compute_file_hash(f)
    doc_id = make_doc_id(file_hash)
    out = PROCESSED / doc_id

    if not out.exists() or not (out / "metadata.json").exists():
        print(f"  {f.name:<50} {'—':<5} {'NOT RUN':<9}")
        not_run += 1
        continue

    meta = json.loads((out / "metadata.json").read_text())
    log  = json.loads((out / "parse_log.json").read_text())
    md   = (out / "document.md").read_text(encoding="utf-8")

    ext = meta["file_type"]
    map_file = {"pdf": "page_map.json", "pptx": "slide_map.json"}.get(ext, "structure_map.json")
    map_data = json.loads((out / map_file).read_text()) if (out / map_file).exists() else []

    lines  = sum(1 for l in md.splitlines() if l.strip())
    status = log["status"]

    icon = {"success": "✓", "warning": "⚠", "failed": "✗"}.get(status, "?")
    name = f.name if len(f.name) <= 50 else f.name[:47] + "..."
    print(f"  {icon} {name:<50} {ext:<5} {status:<9} {meta['parse_method']:<22} {lines:>6} {len(map_data):>7}")

    if log["warnings"]:
        for w in log["warnings"]:
            print(f"      ⚠ {w}")

    if status == "success": ok += 1
    elif status == "warning": warn += 1
    elif status == "failed": fail += 1

print("─" * 108)
print(f"\nResults: {ok} success  {warn} warning  {fail} failed  {not_run} not run  /  {total} total")

if not_run:
    print(f"\n  {not_run} file(s) not processed yet.")
    if any(f.suffix.lower() == ".pdf" for f in files):
        print("  → Run 'make ocr-up && make test-pdf' to process PDF files.")
    if any(f.suffix.lower() == ".docx" for f in files):
        print("  → Run 'make test-docx' to process DOCX files.")
