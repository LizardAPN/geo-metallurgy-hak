"""LLM → Cypher с whitelist-валидацией (только чтение)."""

from __future__ import annotations

import logging
import re

from app.schemas.api import QueryFilters

logger = logging.getLogger(__name__)

# Разрешённые ключевые слова Cypher (read-only)
CYPHER_WHITELIST = re.compile(
    r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|WHERE|RETURN|ORDER\s+BY|LIMIT|SKIP|UNWIND)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Запрещённые мутации
CYPHER_BLACKLIST = re.compile(
    r"\b(CREATE|DELETE|SET|MERGE|REMOVE|DROP|DETACH|FOREACH|CALL\s+\{)\b",
    re.IGNORECASE,
)


def validate_cypher(cypher: str) -> bool:
    """
    Проверить, что Cypher-запрос содержит только read-only операции.

    Args:
        cypher: Сгенерированный Cypher.

    Returns:
        True если запрос безопасен.

    Raises:
        ValueError: Если обнаружены мутации.
    """
    if CYPHER_BLACKLIST.search(cypher):
        raise ValueError("Cypher contains forbidden mutation operations")
    if not CYPHER_WHITELIST.search(cypher):
        raise ValueError("Cypher must start with MATCH or OPTIONAL MATCH")
    return True


def generate_cypher(query: str, filters: QueryFilters | None = None) -> str:
    """
    Сгенерировать Cypher из естественного языка через LLM.

    Args:
        query: Запрос пользователя.
        filters: Фильтры (гео, годы, числовые диапазоны).

    Returns:
        Валидированный read-only Cypher.

    Raises:
        NotImplementedError: Реализация — владелец Senior 1.
    """
    logger.info("generate_cypher query=%r", query[:80])
    raise NotImplementedError(
        "generate_cypher: LLM prompt + validate_cypher whitelist"
    )
