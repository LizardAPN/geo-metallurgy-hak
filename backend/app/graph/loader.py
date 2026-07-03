"""Загрузка JSONL в Neo4j батчами через UNWIND."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from neo4j import Driver

from app.schemas.ontology import Entity, ExtractionResult, Relation

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def load_jsonl(path: Path, driver: Driver) -> tuple[int, int]:
    """
    Загрузить ExtractionResult из JSONL в Neo4j.

    Args:
        path: Путь к data/extracted/*.jsonl
        driver: Neo4j driver.

    Returns:
        Кортеж (число сущностей, число связей).

    Raises:
        NotImplementedError: Полная загрузка — владелец Senior 1.
    """
    logger.info("load_jsonl called for %s", path)
    if not path.exists():
        logger.warning("File not found: %s", path)
        return 0, 0
    raise NotImplementedError(
        "load_jsonl: implement UNWIND batch upsert for entities and relations"
    )


def batch_upsert_entities(driver: Driver, entities: list[Entity]) -> int:
    """
    Батч-вставка/обновление сущностей через UNWIND.

    Args:
        driver: Neo4j driver.
        entities: Список сущностей (до BATCH_SIZE).

    Returns:
        Число обработанных записей.
    """
    if not entities:
        return 0
    rows = [e.model_dump(mode="json") for e in entities]
    query = """
    UNWIND $rows AS row
    CALL apoc.merge.node([row.type], {name_norm: row.name_norm}, row, row) YIELD node
    RETURN count(node) AS cnt
    """
    with driver.session() as session:
        result = session.run(query, rows=rows)
        record = result.single()
        return record["cnt"] if record else 0


def batch_upsert_relations(driver: Driver, relations: list[Relation]) -> int:
    """
    Батч-вставка связей через UNWIND.

    Args:
        driver: Neo4j driver.
        relations: Список связей (до BATCH_SIZE).

    Returns:
        Число обработанных записей.

    Raises:
        NotImplementedError: Реализация merge рёбер — владелец Senior 1.
    """
    logger.info("batch_upsert_relations called, count=%d", len(relations))
    raise NotImplementedError(
        "batch_upsert_relations: implement UNWIND MERGE for typed relationships"
    )


def read_extraction_jsonl(path: Path) -> list[ExtractionResult]:
    """Прочитать JSONL с ExtractionResult."""
    results: list[ExtractionResult] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data: dict[str, Any] = json.loads(line)
            results.append(ExtractionResult.model_validate(data))
    return results
