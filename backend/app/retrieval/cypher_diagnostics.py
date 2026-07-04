"""Диагностика пустых Cypher-результатов: термины name_norm и типы рёбер."""

from __future__ import annotations

import logging
import re
from typing import Any

from neo4j import READ_ACCESS

from app.graph.driver import get_driver

logger = logging.getLogger(__name__)

_NAME_NORM_CONTAINS = re.compile(
    r"name_norm\s+CONTAINS\s+['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_TOLOWER_NAME_NORM_CONTAINS = re.compile(
    r"toLower\s*\([^)]*name_norm[^)]*\)\s+CONTAINS\s+['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_REL_TYPE = re.compile(
    r"(?:-\[|<-\[)[^\]]*?:([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def extract_name_norm_terms(cypher: str) -> list[str]:
    """Извлечь строковые литералы из WHERE name_norm CONTAINS."""
    terms: list[str] = []
    seen: set[str] = set()
    for pattern in (_NAME_NORM_CONTAINS, _TOLOWER_NAME_NORM_CONTAINS):
        for match in pattern.finditer(cypher):
            term = match.group(1).strip().lower()
            if term and term not in seen:
                seen.add(term)
                terms.append(term)
    return terms


def extract_rel_types(cypher: str) -> list[str]:
    """Извлечь типы рёбер из паттернов [:TYPE]."""
    types: list[str] = []
    seen: set[str] = set()
    for match in _REL_TYPE.finditer(cypher):
        rel_type = match.group(1)
        if rel_type not in seen:
            seen.add(rel_type)
            types.append(rel_type)
    return types


def _count_term(term: str) -> int | None:
    driver = get_driver()
    try:
        with driver.session(default_access_mode=READ_ACCESS) as session:
            record = session.run(
                "MATCH (n) WHERE n.name_norm CONTAINS $term RETURN count(n) AS cnt",
                term=term.lower(),
                timeout=10.0,
            ).single()
        return int(record["cnt"]) if record else 0
    except Exception as exc:
        logger.warning("term count failed for %r: %s", term, exc)
        return None


def _count_rel_type(rel_type: str) -> int | None:
    driver = get_driver()
    # rel_type из сгенерированного Cypher — whitelist по имени
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rel_type):
        return None
    try:
        with driver.session(default_access_mode=READ_ACCESS) as session:
            record = session.run(
                f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS cnt",
                timeout=10.0,
            ).single()
        return int(record["cnt"]) if record else 0
    except Exception as exc:
        logger.warning("rel count failed for %s: %s", rel_type, exc)
        return None


def diagnose_empty_cypher(cypher: str) -> dict[str, Any]:
    """
    Проверить, какие термины из WHERE и типы рёбер есть в графе.

    Returns:
        {"term_counts": [...], "rel_counts": [...], "errors": [...]}
    """
    result: dict[str, Any] = {
        "term_counts": [],
        "rel_counts": [],
        "errors": [],
    }
    for term in extract_name_norm_terms(cypher):
        cnt = _count_term(term)
        entry: dict[str, Any] = {"term": term, "count": cnt}
        if cnt is None:
            result["errors"].append(f"term count failed: {term}")
        result["term_counts"].append(entry)

    for rel_type in extract_rel_types(cypher):
        cnt = _count_rel_type(rel_type)
        entry = {"type": rel_type, "count": cnt}
        if cnt is None:
            result["errors"].append(f"rel count failed: {rel_type}")
        result["rel_counts"].append(entry)

    return result
