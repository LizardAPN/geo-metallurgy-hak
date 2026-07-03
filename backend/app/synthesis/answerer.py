"""LLM-синтез обзора с цитатами, консенсусом и противоречиями."""

from __future__ import annotations

import logging

from openai import OpenAI

from app.schemas.api import Citation, RetrievedContext

logger = logging.getLogger(__name__)

SYNTHESIS_SYSTEM_PROMPT = """Ты — аналитик R&D литературы горно-металлургической отрасли.
Сформируй структурированный обзор по контексту из графа знаний.
Каждое утверждение сопровождай ссылкой [doc_id].
Выдели секции: консенсус, противоречия, выводы.
Температура 0.2. Ответ — markdown."""


def synthesize_answer(
    query: str,
    context: RetrievedContext,
    client: OpenAI | None = None,
    model: str = "gpt-4o-mini",
) -> tuple[str, list[Citation]]:
    """
    Синтезировать markdown-ответ с цитатами из RetrievedContext.

    Args:
        query: Запрос пользователя.
        context: Контекст из hybrid retrieval.
        client: OpenAI-совместимый клиент.
        model: Имя модели.

    Returns:
        Кортеж (answer_markdown, citations).

    Raises:
        NotImplementedError: Реализация — владелец Strong.
    """
    logger.info("synthesize_answer query=%r", query[:80])
    raise NotImplementedError(
        "synthesize_answer: LLM synthesis with [doc_id] citations"
    )
