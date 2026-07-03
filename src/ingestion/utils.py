import hashlib
import json
import re
import shutil
from pathlib import Path


def ensure_dirs(*paths):
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def compute_file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def make_doc_id(file_hash: str) -> str:
    return f"doc_{file_hash[:12]}"


def write_json(path: str | Path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_copy_file(src: str | Path, dst: str | Path) -> None:
    shutil.copy2(src, dst)


def normalize_text(text: str) -> str:
    # strip control characters (keep printable + newline + tab)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # remove Docling image placeholders
    text = re.sub(r"<!--\s*image\s*-->", "", text, flags=re.IGNORECASE)
    # collapse runs of spaces (but not newlines)
    text = re.sub(r"[^\S\n]+", " ", text)
    # strip trailing spaces per line
    text = "\n".join(line.rstrip() for line in text.splitlines())
    # collapse runs of 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def join_broken_lines(text: str) -> str:
    """
    Merge lines that look like intra-word or intra-sentence breaks common
    in slide-exported PDFs: a line ending without punctuation that continues
    on the next line with a lowercase letter or continuation word.
    """
    lines = text.splitlines()
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            i + 1 < len(lines)
            and line.strip()
            and lines[i + 1].strip()
            # next line starts lowercase or with a Cyrillic lowercase
            and re.match(r"^[a-zа-яё]", lines[i + 1].strip())
            # current line doesn't end with sentence-ending punctuation
            and not re.search(r"[.!?:;,»)\]—]\s*$", line)
        ):
            result.append(line.rstrip() + " " + lines[i + 1].strip())
            i += 2
        else:
            result.append(line)
            i += 1
    return "\n".join(result)
