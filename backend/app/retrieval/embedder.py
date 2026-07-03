"""Эмбеддинги bge-m3 и косинусный поиск по vector index."""

from __future__ import annotations

import logging
from typing import Any

from neo4j import Driver

logger = logging.getLogger(__name__)


def embed_texts(texts: list[str], model_name: str = "BAAI/bge-m3") -> list[list[float]]:
    """
    Получить эмбеддинги для списка текстов через sentence-transformers.

    Args:
        texts: Список строк.
        model_name: Имя модели (по умолчанию bge-m3, 1024 dim).

    Returns:
        Список векторов.

    Raises:
        NotImplementedError: Реализация — владелец Senior 1.
    """
    logger.info("embed_texts called, count=%d, model=%s", len(texts), model_name)
    raise NotImplementedError(
        "embed_texts: load SentenceTransformer and encode texts"
    )


def vector_search(
    driver: Driver,
    query: str,
    top_k: int = 10,
    model_name: str = "BAAI/bge-m3",
) -> list[dict[str, Any]]:
    """
    Семантический поиск по vector index Neo4j.

    Args:
        driver: Neo4j driver.
        query: Текст запроса пользователя.
        top_k: Число результатов.
        model_name: Модель эмбеддингов.

    Returns:
        Список {node, score}.

    Raises:
        NotImplementedError: Реализация — владелец Senior 1.
    """
    logger.info("vector_search query=%r top_k=%d", query[:80], top_k)
    raise NotImplementedError(
        "vector_search: embed query + CALL db.index.vector.queryNodes"
    )
