"""Парсинг PDF/DOCX в текст и метаданные."""

from __future__ import annotations

import logging
from pathlib import Path

from app.schemas.ontology import ParsedChunk

logger = logging.getLogger(__name__)


def parse_document(path: Path) -> list[ParsedChunk]:
    """
    Разобрать PDF или DOCX документ в список ParsedChunk.

    Использует PyMuPDF для PDF и python-docx для DOCX.
    Каждый элемент содержит текст страницы/секции и метаданные документа.

    Args:
        path: Путь к файлу в data/raw/

    Returns:
        Список ParsedChunk (по одному на страницу/секцию до чанкинга).

    Raises:
        NotImplementedError: Реализация — владелец Mid 2.
        ValueError: Неподдерживаемый формат файла.
    """
    logger.info("parse_document called for %s", path)
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise ValueError(f"Unsupported format: {suffix}")
    raise NotImplementedError(
        "parse_document: implement PDF/DOCX parsing with PyMuPDF and python-docx"
    )
