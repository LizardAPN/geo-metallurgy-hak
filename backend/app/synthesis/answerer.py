"""LLM-синтез обзора с цитатами, консенсусом и противоречиями."""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.llm import get_synthesis_client
from app.schemas.api import Contradiction, RetrievedContext
from app.schemas.ontology import RelationType
from app.synthesis.prompts import SYNTHESIS_SYSTEM

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 12000
MAX_CHUNK_CHARS = 800
MAX_CHUNKS = 8

_DOC_CITATION = re.compile(r"\[doc:([^\]]+)\]")
_NUMERIC_EDGE_TYPES = frozenset(
    {RelationType.OPERATES_AT_CONDITION, RelationType.HAS_PROPERTY}
)


def extract_graph_facts(ctx: RetrievedContext) -> list[dict]:
    """Numeric facts из cypher_results и numeric edges."""
    facts: list[dict] = []
    seen: set[str] = set()

    for row in ctx.cypher_results:
        if not row.get("parameter"):
            continue
        key = f"{row.get('name')}:{row.get('parameter')}:{row.get('value')}"
        if key in seen:
            continue
        seen.add(key)
        facts.append(row)

    for edge in ctx.edges:
        if edge.type not in _NUMERIC_EDGE_TYPES:
            continue
        props = edge.properties
        if not props.get("parameter"):
            continue
        key = f"{edge.source}:{props.get('parameter')}:{props.get('value')}"
        if key in seen:
            continue
        seen.add(key)
        facts.append(
            {
                "name": edge.source,
                "parameter": props.get("parameter"),
                "op": props.get("operator", "="),
                "value": props.get("value"),
                "value_min": props.get("value_min"),
                "value_max": props.get("value_max"),
                "unit": props.get("unit", ""),
                "confidence": props.get("confidence", 0.0),
                "sources": [{"doc_id": props.get("source_doc")}],
            }
        )
    return facts


def _format_fact(row: dict) -> str:
    name = row.get("name") or row.get("type") or "?"
    param = row.get("parameter") or "?"
    op = row.get("op") or row.get("operator") or "="
    unit = row.get("unit") or ""
    conf = row.get("confidence", 0.0)

    if row.get("value") is not None:
        value_str = f"{row['value']}{unit}"
    elif row.get("value_min") is not None or row.get("value_max") is not None:
        vmin = row.get("value_min", "")
        vmax = row.get("value_max", "")
        value_str = f"{vmin}–{vmax}{unit}"
    else:
        value_str = f"?{unit}"

    sources = row.get("sources") or []
    doc_ids: list[str] = []
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, dict) and src.get("doc_id"):
                doc_ids.append(str(src["doc_id"]))
    if not doc_ids and row.get("doc_id"):
        doc_ids.append(str(row["doc_id"]))
    src_str = ", ".join(f"doc:{d}" for d in doc_ids) if doc_ids else "doc:unknown"

    return f"«{name}» — {param} {op} {value_str} (confidence {conf}, источники: {src_str})"


def _trim_at_sentence(text: str, max_len: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_len:
        return collapsed
    snippet = collapsed[:max_len]
    for sep in (". ", "! ", "? "):
        idx = snippet.rfind(sep)
        if idx > max_len // 2:
            return snippet[: idx + 1].rstrip()
    return snippet.rstrip() + "…"


def _format_chunk(row: dict) -> str:
    doc_id = row.get("doc_id") or "unknown"
    title = row.get("title") or "Без названия"
    year = row.get("year") or "?"
    text = _trim_at_sentence(str(row.get("text") or ""), MAX_CHUNK_CHARS)
    return f"[doc:{doc_id}] {title} ({year}): {text}"


def build_synthesis_context(query: str, ctx: RetrievedContext) -> str:
    """Собрать user-сообщение с бюджетом символов."""
    facts = extract_graph_facts(ctx)
    fact_lines = [_format_fact(f) for f in facts]
    facts_block = "[ФАКТЫ ГРАФА]\n" + "\n".join(fact_lines) if fact_lines else "[ФАКТЫ ГРАФА]\n(нет)"

    contradictions = extract_contradictions(ctx)
    contradictions_block = ""
    if contradictions:
        lines = [f"- {c.source_a} vs {c.source_b}: {c.description}" for c in contradictions]
        contradictions_block = "[ЗАФИКСИРОВАННЫЕ ПРОТИВОРЕЧИЯ]\n" + "\n".join(lines)

    chunk_lines: list[str] = []
    budget_used = len(facts_block) + len(contradictions_block) + len(query) + 200
    for row in ctx.chunks[:MAX_CHUNKS]:
        line = _format_chunk(row)
        if budget_used + len(line) > MAX_CONTEXT_CHARS:
            break
        chunk_lines.append(line)
        budget_used += len(line) + 1

    chunks_block = "[ФРАГМЕНТЫ ДОКУМЕНТОВ]\n" + (
        "\n".join(chunk_lines) if chunk_lines else "(нет)"
    )
    parts = [f"Вопрос: {query}", facts_block]
    if contradictions_block:
        parts.append(contradictions_block)
    parts.append(chunks_block)
    return "\n\n".join(parts)


def _valid_doc_ids(ctx: RetrievedContext) -> set[str]:
    ids: set[str] = set()
    for row in ctx.chunks:
        if row.get("doc_id"):
            ids.add(str(row["doc_id"]))
    for row in ctx.cypher_results:
        if row.get("doc_id"):
            ids.add(str(row["doc_id"]))
        for src in row.get("sources") or []:
            if isinstance(src, dict) and src.get("doc_id"):
                ids.add(str(src["doc_id"]))
    return ids


def strip_invalid_citations(answer: str, valid_doc_ids: set[str]) -> str:
    """Удалить [doc:...] с несуществующими doc_id."""

    def _replace(match: re.Match[str]) -> str:
        doc_id = match.group(1)
        if doc_id in valid_doc_ids:
            return match.group(0)
        logger.warning("stripping hallucinated citation doc:%s", doc_id)
        return ""

    return _DOC_CITATION.sub(_replace, answer)


def extract_contradictions(ctx: RetrievedContext) -> list[Contradiction]:
    """Собрать противоречия из рёбер CONTRADICTS."""
    node_names = {n.id: n.name for n in ctx.nodes}
    contradictions: list[Contradiction] = []
    for edge in ctx.edges:
        if edge.type != RelationType.CONTRADICTS:
            continue
        src_name = node_names.get(edge.source, edge.source)
        tgt_name = node_names.get(edge.target, edge.target)
        note = edge.properties.get("note") or edge.properties.get("description")
        contradictions.append(
            Contradiction(
                claim_a=src_name,
                claim_b=tgt_name,
                source_a=edge.source,
                source_b=edge.target,
                description=str(note) if note else "Противоречие между источниками",
            )
        )
    return contradictions


async def synthesize(query: str, ctx: RetrievedContext) -> str:
    """Синтезировать markdown-ответ с цитатами из RetrievedContext."""
    llm = get_synthesis_client()
    user = build_synthesis_context(query, ctx)
    answer = await llm.complete(
        SYNTHESIS_SYSTEM,
        user,
        temperature=0.2,
        max_tokens=2500,
        model=settings.effective_synthesis_model,
    )
    valid_ids = _valid_doc_ids(ctx)
    return strip_invalid_citations(answer.strip(), valid_ids)
