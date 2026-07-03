"""Детекция пробелов знаний: комбинации сущностей без Experiment-связей."""

from __future__ import annotations

import logging

from app.schemas.api import KnowledgeGap, RetrievedContext

logger = logging.getLogger(__name__)


def detect_gaps(
    context: RetrievedContext,
    query_entities: list[str] | None = None,
) -> list[KnowledgeGap]:
    """
    Найти пробелы: комбинации условий без связанных Experiment.

    Args:
        context: Контекст retrieval (узлы и рёбра).
        query_entities: Сущности, извлечённые из запроса (опционально).

    Returns:
        Список KnowledgeGap.

    Raises:
        NotImplementedError: Реализация — владелец Strong.
    """
    logger.info(
        "detect_gaps entities=%s, nodes=%d",
        query_entities,
        len(context.nodes),
    )
    raise NotImplementedError(
        "detect_gaps: find entity combinations missing Experiment links"
    )
