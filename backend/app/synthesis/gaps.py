"""Детекция пробелов знаний и рекомендация экспертов (детерминированно, без LLM)."""

from __future__ import annotations

import logging
import re

from neo4j import READ_ACCESS

from app.graph.driver import get_driver
from app.schemas.api import KnowledgeGap, RecommendedExpert

logger = logging.getLogger(__name__)

ANCHOR_LABELS = ["Process", "Material"]
MAX_GAPS = 3
MAX_ANCHORS = 5
MIN_ANCHOR_LEN = 5
MIN_ANCHOR_DEGREE = 3
_REDUNDANT_PREFIX_LEN = 12
_ANCHOR_JUNK = re.compile(r"[\d%=°]")

_STOPWORDS = frozenset(
    {
        "какие", "какой", "какая", "какое", "найди", "найти", "где", "кто",
        "что", "как", "при", "для", "или", "это", "они", "все", "всех",
        "the", "and", "for", "with", "from", "that", "this", "which",
        "after", "before", "year", "years", "find", "show",
    }
)

_RESOLVE_ANCHORS = """
MATCH (n)
WHERE any(l IN labels(n) WHERE l IN $labels)
  AND (
    toLower(n.name_norm) CONTAINS $term
    OR any(a IN coalesce(n.aliases, []) WHERE toLower(a) CONTAINS $term)
  )
WITH n, count { (n)--() } AS degree
WHERE degree >= $min_degree
RETURN n.name AS name, n.name_norm AS name_norm, labels(n)[0] AS label
LIMIT 3
"""

_CHECK_GAP = """
MATCH (a {name_norm: $x}), (b {name_norm: $y})
WHERE id(a) < id(b)
OPTIONAL MATCH (e:Experiment)-[]->(a)
WHERE (e)-[]->(b)
WITH a, b, count(e) AS n
WHERE n = 0
RETURN a.name AS name_a, b.name AS name_b
LIMIT 1
"""

_EXPERTS = """
MATCH (p:Publication)-[:authored_by]->(ex:Expert)
WHERE p.doc_id IN $ids
RETURN ex.name AS name,
       ex.affiliation AS affiliation,
       count(p) AS works,
       collect(DISTINCT p.title)[..3] AS top_publications
ORDER BY works DESC
LIMIT 5
"""


def _query_terms(query: str) -> list[str]:
    tokens = re.findall(r"[\w\u0400-\u04FF]+", query.lower())
    return [t for t in tokens if len(t) >= 4 and t not in _STOPWORDS]


def _is_valid_anchor(name_norm: str, label: str, term: str) -> bool:
    """Якорь годен: label Process|Material, длина >= 5, без цифр/символов, матч на термин запроса."""
    nn = name_norm.strip().lower()
    if label not in ANCHOR_LABELS:
        return False
    if len(nn) < MIN_ANCHOR_LEN:
        return False
    if _ANCHOR_JUNK.search(nn):
        return False
    return term in nn or nn in term


def _is_redundant_pair(x: str, y: str) -> bool:
    """Пара — варианты одного термина: подстрока или совпадение первых 12 символов."""
    a = x.strip().lower()
    b = y.strip().lower()
    if a in b or b in a:
        return True
    return a[:_REDUNDANT_PREFIX_LEN] == b[:_REDUNDANT_PREFIX_LEN]


def resolve_anchor_entities(query: str) -> list[dict[str, str]]:
    """Найти якорные сущности Process/Material по терминам запроса."""
    terms = _query_terms(query)
    if not terms:
        return []

    driver = get_driver()
    anchors: dict[str, dict[str, str]] = {}
    try:
        with driver.session(default_access_mode=READ_ACCESS) as session:
            for term in terms:
                if len(anchors) >= MAX_ANCHORS:
                    break
                records = session.run(
                    _RESOLVE_ANCHORS,
                    labels=ANCHOR_LABELS,
                    term=term,
                    min_degree=MIN_ANCHOR_DEGREE,
                    timeout=10.0,
                )
                for record in records:
                    name_norm = str(record["name_norm"])
                    label = str(record["label"])
                    if name_norm in anchors:
                        continue
                    if not _is_valid_anchor(name_norm, label, term):
                        continue
                    anchors[name_norm] = {
                        "name": str(record["name"]),
                        "name_norm": name_norm,
                        "label": label,
                    }
    except Exception as exc:
        logger.warning("resolve_anchor_entities failed: %s", exc)
    return list(anchors.values())[:MAX_ANCHORS]


def find_gaps(query_entities: list[str]) -> list[KnowledgeGap]:
    """
    Найти пробелы: пары якорных сущностей без общего Experiment.

    query_entities — name_norm якорей (обе должны быть в графе).
    """
    if len(query_entities) < 2:
        return []

    driver = get_driver()
    gaps: list[KnowledgeGap] = []
    try:
        with driver.session(default_access_mode=READ_ACCESS) as session:
            for i, x in enumerate(query_entities):
                if len(gaps) >= MAX_GAPS:
                    break
                for y in query_entities[i + 1 :]:
                    if len(gaps) >= MAX_GAPS:
                        break
                    if _is_redundant_pair(x, y):
                        continue
                    record = session.run(
                        _CHECK_GAP,
                        x=x,
                        y=y,
                        timeout=10.0,
                    ).single()
                    if record is None:
                        continue
                    name_a = str(record["name_a"])
                    name_b = str(record["name_b"])
                    gaps.append(
                        KnowledgeGap(
                            entities=[name_a, name_b],
                            missing_link="Experiment",
                            description=f"Не найдено экспериментов: {name_a} + {name_b}",
                        )
                    )
    except Exception as exc:
        logger.warning("find_gaps failed: %s", exc)
    return gaps


def find_gaps_from_query(query: str) -> list[KnowledgeGap]:
    """Resolve anchors from query text, then find gaps."""
    anchors = resolve_anchor_entities(query)
    if len(anchors) < 2:
        return []
    name_norms = [a["name_norm"] for a in anchors]
    return find_gaps(name_norms)


def recommend_experts(doc_ids: list[str]) -> list[RecommendedExpert]:
    """Рекомендовать экспертов по top-документам ответа."""
    if not doc_ids:
        return []

    driver = get_driver()
    experts: list[RecommendedExpert] = []
    try:
        with driver.session(default_access_mode=READ_ACCESS) as session:
            records = session.run(_EXPERTS, ids=doc_ids, timeout=10.0)
            for record in records:
                top_pubs = record.get("top_publications") or []
                experts.append(
                    RecommendedExpert(
                        name=str(record["name"]),
                        affiliation=record.get("affiliation"),
                        publication_count=int(record["works"] or 0),
                        top_publications=[str(p) for p in top_pubs if p],
                    )
                )
    except Exception as exc:
        logger.warning("recommend_experts failed: %s", exc)
    return experts
