"""POST /api/query — главный эндпоинт поисково-аналитической системы."""

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.graph import build_publication_star, expand_chunks_1hop
from app.config import settings
from app.retrieval import vector_search
from app.schemas.api import Citation, GraphSubset, QueryMeta, QueryRequest, QueryResponse

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_SNIPPET_CHARS = 400


def synthesize(query: str, chunks: list[dict[str, Any]], facts: list[dict[str, Any]]) -> str:
    """Placeholder for the future synthesis module."""
    raise NotImplementedError("Synthesis module is not connected yet")


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
        warning = "Фильтр geo пока не применяется в vector search."
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


def _numeric_facts(graph_subset: GraphSubset) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    numeric_keys = {"parameter", "operator", "value", "value_min", "value_max", "unit"}
    for edge in graph_subset.edges:
        if numeric_keys.intersection(edge.properties):
            facts.append({"edge_id": edge.id, **edge.properties})
    return facts


def _mode(graph_enabled: bool, graph_subset: GraphSubset, synthesis_used: bool) -> str:
    if synthesis_used:
        return "full"
    if graph_enabled and graph_subset.nodes:
        return "vector+graph"
    return "vector"


def _run_pipeline(request: QueryRequest) -> QueryResponse:
    started = time.perf_counter()
    vector_filters, warning, min_confidence = _filters_to_vector_params(request)

    try:
        chunks = vector_search.search(request.query, top_k=10, filters=vector_filters)
    except Exception as exc:
        logger.exception("Vector search failed")
        raise HTTPException(
            status_code=503,
            detail="Поиск по корпусу сейчас недоступен. Проверьте Neo4j и повторите запрос.",
        ) from exc

    graph_subset = build_publication_star(chunks)
    graph_used = False
    if settings.feature_graph:
        try:
            expanded = expand_chunks_1hop(
                [str(row["chunk_id"]) for row in chunks if row.get("chunk_id")],
                min_confidence=min_confidence,
            )
            if expanded.nodes:
                graph_subset = expanded
                graph_used = True
        except Exception as exc:
            logger.warning("Graph expansion unavailable: %s", exc)
            graph_warning = "Графовое расширение временно недоступно; показаны документы из vector search."
            warning = f"{warning} {graph_warning}" if warning else graph_warning

    facts = _numeric_facts(graph_subset)
    synthesis_used = False
    if settings.feature_synthesis:
        try:
            answer_markdown = synthesize(request.query, chunks, facts)
            synthesis_used = True
        except NotImplementedError as exc:
            logger.info("Synthesis flag enabled but module is not ready: %s", exc)
            synth_warning = "Synthesis включён, но модуль ещё не подключён; показан extractive-ответ."
            warning = f"{warning} {synth_warning}" if warning else synth_warning
            answer_markdown = _build_extractive_answer(chunks)
        except Exception as exc:
            logger.warning("Synthesis failed: %s", exc)
            synth_warning = "Synthesis завершился ошибкой; показан extractive-ответ."
            warning = f"{warning} {synth_warning}" if warning else synth_warning
            answer_markdown = _build_extractive_answer(chunks)
    else:
        answer_markdown = _build_extractive_answer(chunks)

    took_ms = int((time.perf_counter() - started) * 1000)
    return QueryResponse(
        answer_markdown=answer_markdown,
        citations=_build_citations(chunks),
        graph_subset=graph_subset,
        contradictions=[],
        knowledge_gaps=[],
        recommended_experts=[],
        mock=False,
        warning=warning,
        meta=QueryMeta(
            mode=_mode(graph_used, graph_subset, synthesis_used),
            took_ms=took_ms,
        ),
    )


@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    """
    Обработать запрос пользователя.

    Всегда выполняет vector search. Graph/synthesis включаются feature-флагами.
    """
    logger.info("query: %r", request.query[:120])
    return _run_pipeline(request)
