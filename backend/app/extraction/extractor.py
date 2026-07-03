"""LLM-извлечение сущностей и связей с валидацией Pydantic."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.extraction.prompts import (
    EXTRACTION_FEW_SHOT,
    EXTRACTION_SYSTEM_PROMPT,
    EXTRACTION_USER_TEMPLATE,
)
from app.schemas.ontology import ExtractionResult, ParsedChunk

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_llm(client: OpenAI, model: str, messages: list[dict[str, str]]) -> str:
    """Вызов LLM с retry через tenacity."""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Empty LLM response")
    return content


def extract_from_chunk(
    chunk: ParsedChunk,
    client: OpenAI,
    model: str = "gpt-4o-mini",
) -> ExtractionResult:
    """
    Извлечь сущности и связи из чанка через LLM.

    Валидирует ответ через Pydantic ExtractionResult.
    При ошибке валидации — retry (до 3 попыток через tenacity).

    Args:
        chunk: Распарсенный чанк документа.
        client: OpenAI-совместимый клиент.
        model: Имя модели.

    Returns:
        ExtractionResult с entities и relations.

    Raises:
        NotImplementedError: Полный pipeline — владелец Senior 2.
    """
    logger.info("extract_from_chunk called for chunk_id=%s", chunk.chunk_id)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
    ]
    for example in EXTRACTION_FEW_SHOT:
        messages.append({"role": "user", "content": example["input"]})
        messages.append({"role": "assistant", "content": example["output"]})
    messages.append(
        {
            "role": "user",
            "content": EXTRACTION_USER_TEMPLATE.format(
                doc_id=chunk.doc_id, text=chunk.text[:4000]
            ),
        }
    )

    raise NotImplementedError(
        "extract_from_chunk: wire _call_llm + ExtractionResult.model_validate"
    )


def parse_extraction_json(raw: str, doc_id: str) -> ExtractionResult:
    """Распарсить и валидировать JSON ответа LLM."""
    data: dict[str, Any] = json.loads(raw)
    data["doc_id"] = doc_id
    return ExtractionResult.model_validate(data)
