"""Справочник generic-терминов, исключаемых при загрузке графа."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STOP_ENTITIES_PATH = REPO_ROOT / "data" / "reference" / "stop_entities.json"

_DIGITS_ONLY = re.compile(r"^\d+$")
_LATIN_FRAGMENT = re.compile(r"^[a-z0-9]{1,6}$")


def load_stop_entities(path: Path = STOP_ENTITIES_PATH) -> frozenset[str]:
    """Загрузить нормализованный набор стоп-терминов (lowercase)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    terms = data.get("terms", [])
    return frozenset(str(t).strip().lower() for t in terms if str(t).strip())


def is_suspicious_name_norm(name_norm: str) -> bool:
    """Эвристика OCR/мусорных name_norm: короткие, только цифры, латиница-обрубки."""
    s = name_norm.strip().lower()
    if len(s) < 4:
        return True
    if _DIGITS_ONLY.match(s):
        return True
    if _LATIN_FRAGMENT.match(s) and not any("\u0400" <= c <= "\u04ff" for c in s):
        return True
    return False
