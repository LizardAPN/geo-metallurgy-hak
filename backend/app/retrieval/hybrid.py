"""Гибридный retrieval: слияние результатов через RRF."""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.api import RetrievedContext
from app.schemas.ontology import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    k: int = 60,
    id_key: str = "id",
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion для объединения ранжированных списков.

    score(d) = sum(1 / (k + rank(d)))

    Args:
        ranked_lists: Списки результатов от vector search и text2cypher.
        k: Константа RRF (обычно 60).
        id_key: Ключ идентификатора в словаре результата.

    Returns:
        Объединённый отсортированный список.
    """
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    for result_list in ranked_lists:
        for rank, item in enumerate(result_list, start=1):
            item_id = str(item.get(id_key, rank))
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
            items[item_id] = item
    fused = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    return [{**items[item_id], "rrf_score": scores[item_id]} for item_id in fused]


def hybrid_retrieve(
    vector_results: list[dict[str, Any]],
    cypher_results: list[dict[str, Any]],
    top_k: int = 20,
) -> RetrievedContext:
    """
    Слить vector и cypher результаты в RetrievedContext.

    Args:
        vector_results: Результаты vector_search.
        cypher_results: Результаты text2cypher.
        top_k: Число результатов после fusion.

    Returns:
        RetrievedContext для synthesis.

    Raises:
        NotImplementedError: Полный pipeline с 1-hop окружением — Senior 1.
    """
    fused = reciprocal_rank_fusion([vector_results, cypher_results])[:top_k]
    logger.info("hybrid_retrieve fused %d items", len(fused))
    raise NotImplementedError(
        "hybrid_retrieve: expand 1-hop neighborhood into RetrievedContext"
    )


def build_context_from_fused(
    fused: list[dict[str, Any]],
    nodes: list[GraphNode],
    edges: list[GraphEdge],
) -> RetrievedContext:
    """Собрать RetrievedContext из уже полученных узлов и рёбер."""
    return RetrievedContext(
        nodes=nodes,
        edges=edges,
        chunks=[item.get("chunk", {}) for item in fused if "chunk" in item],
        cypher_results=fused,
    )
