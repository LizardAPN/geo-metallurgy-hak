"""Нормализация терминов RU/EN и словарь синонимов."""

from __future__ import annotations

import logging
import re

from app.schemas.ontology import Entity

logger = logging.getLogger(__name__)

# Словарь синонимов RU↔EN (пополняется вручную из справочников корпуса)
SYNONYMS: dict[str, str] = {
    "обессоливание": "обессоливание",
    "desalination": "обессоливание",
    "деминерализация": "обессоливание",
    "выщелачивание": "выщелачивание",
    "leaching": "выщелачивание",
    "heap leaching": "кучное выщелачивание",
    "кучное выщелачивание": "кучное выщелачивание",
    "флотация": "флотация",
    "flotation": "флотация",
    "обратный осмос": "обратный осмос",
    "reverse osmosis": "обратный осмос",
    "ионный обмен": "ионный обмен",
    "ion exchange": "ионный обмен",
}


def normalize_name(name: str) -> str:
    """
    Привести термин к каноническому русскому имени (name_norm).

    Args:
        name: Исходное имя (RU или EN).

    Returns:
        Канонический термин для constraint уникальности в Neo4j.
    """
    key = re.sub(r"\s+", " ", name.strip().lower())
    return SYNONYMS.get(key, name.strip())


def normalize_entity(entity: Entity) -> Entity:
    """
    Заполнить name_norm и aliases для сущности.

    Args:
        entity: Сущность после extraction.

    Returns:
        Сущность с обновлённым name_norm.
    """
    canonical = normalize_name(entity.name)
    aliases = list({*entity.aliases, entity.name})
    if canonical != entity.name and canonical not in aliases:
        aliases.append(canonical)
    return entity.model_copy(update={"name_norm": canonical, "aliases": aliases})
