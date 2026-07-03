"""Параметризованные Cypher-запросы к графу."""

from __future__ import annotations

import logging
from typing import Any

from neo4j import Driver

from app.schemas.ontology import NumericConstraint

logger = logging.getLogger(__name__)


def get_neighbors(
    driver: Driver,
    node_id: str,
    depth: int = 1,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """
    Получить соседей узла на заданной глубине.

    Args:
        driver: Neo4j driver.
        node_id: ID узла.
        depth: Глубина обхода (1 = 1-hop).
        min_confidence: Минимальный confidence на рёбрах.

    Returns:
        Список записей {node, rel, neighbor}.

    Raises:
        NotImplementedError: Реализация — владелец Senior 1.
    """
    logger.info("get_neighbors node_id=%s depth=%d", node_id, depth)
    raise NotImplementedError("get_neighbors: implement parameterized Cypher")


def find_paths(
    driver: Driver,
    source_id: str,
    target_id: str,
    max_depth: int = 4,
) -> list[dict[str, Any]]:
    """
    Найти пути между двумя узлами.

    Args:
        driver: Neo4j driver.
        source_id: ID начального узла.
        target_id: ID конечного узла.
        max_depth: Максимальная длина пути.

    Returns:
        Список путей.

    Raises:
        NotImplementedError: Реализация — владелец Senior 1.
    """
    logger.info("find_paths %s -> %s", source_id, target_id)
    raise NotImplementedError("find_paths: implement shortestPath / apoc.path")


def filter_by_numeric_constraint(
    driver: Driver,
    constraint: NumericConstraint,
    entity_type: str = "Experiment",
) -> list[dict[str, Any]]:
    """
    Найти сущности, удовлетворяющие числовому ограничению.

    Args:
        driver: Neo4j driver.
        constraint: Числовой фильтр (parameter, operator, value, unit).
        entity_type: Label узла для поиска.

    Returns:
        Список подходящих узлов/рёбер.

    Raises:
        NotImplementedError: Реализация — владелец Senior 1.
    """
    logger.info(
        "filter_by_numeric_constraint %s %s %s %s",
        constraint.parameter,
        constraint.operator,
        constraint.value,
        constraint.unit,
    )
    raise NotImplementedError(
        "filter_by_numeric_constraint: implement numeric edge property filter"
    )
