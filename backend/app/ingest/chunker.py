"""Чанкинг текста с overlap и сохранение в data/parsed/."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.schemas.ontology import ChunkMetadata, ParsedChunk

logger = logging.getLogger(__name__)


def chunk_text(
    text: str,
    doc_id: str,
    source_path: str,
    metadata: ChunkMetadata | None = None,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[ParsedChunk]:
    """
    Разбить текст на перекрывающиеся чанки.

    Args:
        text: Полный текст документа.
        doc_id: Идентификатор документа.
        source_path: Путь к исходному файлу.
        metadata: Метаданные документа.
        chunk_size: Размер чанка в символах.
        overlap: Перекрытие между чанками.

    Returns:
        Список ParsedChunk.

    Raises:
        NotImplementedError: Полная реализация — владелец Mid 2.
    """
    logger.info("chunk_text called for doc_id=%s, len=%d", doc_id, len(text))
    raise NotImplementedError(
        "chunk_text: implement sliding-window chunking with overlap"
    )


def write_jsonl(chunks: list[ParsedChunk], out_path: Path) -> None:
    """
    Записать чанки в JSONL (одна строка = один ParsedChunk).

    Args:
        chunks: Список чанков.
        out_path: Путь к выходному файлу в data/parsed/.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk.model_dump_json() + "\n")
    logger.info("Wrote %d chunks to %s", len(chunks), out_path)
