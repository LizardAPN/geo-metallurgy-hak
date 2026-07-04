"""POST /api/query — главный эндпоинт поисково-аналитической системы."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.graph.convert import build_publication_star
from app.retrieval import hybrid, vector_search
from app.schemas.api import (
    Citation,
    GraphSubset,
    QueryMeta,
    QueryRequest,
    QueryResponse,
    RetrievedContext,
)
from app.synthesis.answerer import extract_contradictions, synthesize
from app.synthesis.gaps import find_gaps_from_query, recommend_experts

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_SNIPPET_CHARS = 400
SYNTHESIS_TIMEOUT_SEC = 30


def _filters_to_vector_params(request: QueryRequest) -> tuple[dict[str, Any], str | None, float]:
    filters = request.filters
    if filters is None:
        return {}, None, 0.0

    params: dict[str, Any] = {}
    warning: str | None = None
    if filters.year_range is not None:
        year_min, year_max = filters.year_range
        params["year_min"] = year_min
        params["year_max"] = year_max
    if filters.geo:
        params["geo"] = filters.geo
    params["min_confidence"] = filters.min_confidence
    if filters.numeric_filters:
        params["numeric_filters"] = [
            nf.model_dump() if hasattr(nf, "model_dump") else nf
            for nf in filters.numeric_filters
        ]
    return params, warning, filters.min_confidence


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _score(value: Any) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(float(value), 1.0))
    return 0.0


def _build_citations(chunks: list[dict[str, Any]]) -> list[Citation]:
    citations: list[Citation] = []
    seen_chunks: set[str] = set()
    for row in chunks:
        chunk_id = _as_text(row.get("chunk_id"))
        if chunk_id in seen_chunks:
            continue
        seen_chunks.add(chunk_id)
        text = _as_text(row.get("text"))
        citations.append(
            Citation(
                doc_id=_as_text(row.get("doc_id"), "unknown"),
                chunk_id=chunk_id or None,
                title=_as_text(row.get("title"), "Без названия"),
                snippet=text[:MAX_SNIPPET_CHARS],
                confidence=_score(row.get("score")),
                page=row.get("page"),
                score=row.get("score"),
                year=row.get("year"),
                geography=_as_text(row.get("geography"), "UNKNOWN"),
            )
        )
    return citations


def _trim_chunk(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= MAX_SNIPPET_CHARS:
        return collapsed
    return f"{collapsed[:MAX_SNIPPET_CHARS].rstrip()}…"


def _build_extractive_answer(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return "## Ничего не найдено\n\nПопробуйте переформулировать запрос или расширить фильтры."

    blocks = ["## Найдено по запросу"]
    for row in chunks[:5]:
        title = _as_text(row.get("title"), "Без названия")
        year = row.get("year") or "год не указан"
        venue_or_type = row.get("venue") or row.get("doc_type") or "тип не указан"
        doc_id = _as_text(row.get("doc_id"), "unknown")
        text = _trim_chunk(_as_text(row.get("text")))
        blocks.append(
            f"**{title}** ({year}, {venue_or_type}) [doc:{doc_id}]\n{text}"
        )
    return "\n\n".join(blocks)


def _mode(
    retrieval_mode: str,
    synthesis_used: bool,
    graph_subset: GraphSubset,
) -> str:
    if synthesis_used:
        return "full"
    if retrieval_mode in ("vector+graph", "graph") and graph_subset.nodes:
        return "vector+graph"
    return "vector"


async def _run_pipeline(request: QueryRequest) -> QueryResponse:
    started = time.perf_counter()
    vector_filters, warning, _min_confidence = _filters_to_vector_params(request)
    ctx: RetrievedContext | None = None
    retrieval_mode = "vector"
    chunks: list[dict[str, Any]] = []

    if settings.feature_graph:
        try:
            ctx, retrieval_mode = await hybrid.retrieve(
                request.query, vector_filters, top_k=12
            )
            chunks = ctx.chunks
            graph_subset = GraphSubset(nodes=ctx.nodes, edges=ctx.edges)
            if not graph_subset.nodes and chunks:
                graph_subset = build_publication_star(chunks)
        except Exception as exc:
            logger.exception("Hybrid retrieval failed")
            raise HTTPException(
                status_code=503,
                detail="Поиск по корпусу сейчас недоступен. Проверьте Neo4j и повторите запрос.",
            ) from exc
    else:
        try:
            chunks = await asyncio.to_thread(
                vector_search.search, request.query, 10, vector_filters
            )
        except Exception as exc:
            logger.exception("Vector search failed")
            raise HTTPException(
                status_code=503,
                detail="Поиск по корпусу сейчас недоступен. Проверьте Neo4j и повторите запрос.",
            ) from exc
        graph_subset = build_publication_star(chunks)
        ctx = RetrievedContext(chunks=chunks, nodes=graph_subset.nodes, edges=graph_subset.edges)

    synthesis_used = False
    if settings.feature_synthesis and ctx is not None:
        try:
            answer_markdown = await asyncio.wait_for(
                synthesize(request.query, ctx),
                timeout=SYNTHESIS_TIMEOUT_SEC,
            )
            synthesis_used = True
        except TimeoutError:
            logger.warning("Synthesis timed out after %ds", SYNTHESIS_TIMEOUT_SEC)
            synth_warning = "Synthesis превысил таймаут; показан extractive-ответ."
            warning = f"{warning} {synth_warning}" if warning else synth_warning
            answer_markdown = _build_extractive_answer(chunks)
        except Exception as exc:
            logger.warning("Synthesis failed: %s", exc)
            synth_warning = "Synthesis завершился ошибкой; показан extractive-ответ."
            warning = f"{warning} {synth_warning}" if warning else synth_warning
            answer_markdown = _build_extractive_answer(chunks)
    else:
        answer_markdown = _build_extractive_answer(chunks)

    contradictions = extract_contradictions(ctx) if ctx else []
    knowledge_gaps = find_gaps_from_query(request.query) if settings.feature_graph else []
    doc_ids = list(dict.fromkeys(_as_text(c.doc_id) for c in _build_citations(chunks) if c.doc_id))
    recommended = recommend_experts(doc_ids[:10]) if settings.feature_graph else []

    took_ms = int((time.perf_counter() - started) * 1000)
    return QueryResponse(
        answer_markdown=answer_markdown,
        citations=_build_citations(chunks),
        graph_subset=graph_subset,
        contradictions=contradictions,
        knowledge_gaps=knowledge_gaps,
        recommended_experts=recommended,
        mock=False,
        warning=warning,
        meta=QueryMeta(
            mode=_mode(retrieval_mode, synthesis_used, graph_subset),
            took_ms=took_ms,
        ),
    )


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """
    Обработать запрос пользователя.

    Vector search всегда; graph/synthesis включаются feature-флагами.
    """
    logger.info("query: %r", request.query[:120])
    return await _run_pipeline(request)
