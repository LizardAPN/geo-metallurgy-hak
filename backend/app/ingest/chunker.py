"""Чанкинг блоков и сохранение в data/parsed/."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import langdetect

from app.ingest.types import Block
from app.schemas.ontology import ParsedChunk

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150


def _detect_lang(text: str) -> str:
  try:
    code = langdetect.detect(text)
    if code.startswith("ru"):
      return "ru"
    if code.startswith("en"):
      return "en"
  except langdetect.LangDetectException:
    pass
  return "ru"


def _chunk_paragraphs(
  indexed_blocks: list[tuple[int, Block]],
  *,
  doc_id: str,
  section: str,
  file_name: str,
  source_key: str,
) -> list[ParsedChunk]:
  if not indexed_blocks:
    return []

  parts: list[str] = []
  part_start_idx: list[int] = []
  for idx, block in indexed_blocks:
    parts.append(block.text)
    part_start_idx.append(idx)

  full_text = "\n\n".join(parts)
  if not full_text.strip():
    return []

  chunks: list[ParsedChunk] = []
  offsets = []
  pos = 0
  for i, part in enumerate(parts):
    offsets.append((pos, part_start_idx[i]))
    pos += len(part) + 2

  start = 0
  text_len = len(full_text)

  while start < text_len:
    end = min(start + CHUNK_SIZE, text_len)
    if end < text_len:
      boundary = full_text.rfind("\n\n", start, end)
      if boundary > start:
        end = boundary
      else:
        boundary = full_text.rfind("\n", start, end)
        if boundary > start:
          end = boundary

    chunk_text = full_text[start:end].strip()
    if chunk_text:
      start_idx = indexed_blocks[0][0]
      for off, block_idx in reversed(offsets):
        if off <= start:
          start_idx = block_idx
          break
      page = next(
        (b.page for i, b in indexed_blocks if i == start_idx and b.page is not None),
        next((b.page for _, b in indexed_blocks if b.page is not None), None),
      )
      chunks.append(
        ParsedChunk(
          doc_id=doc_id,
          chunk_id=f"{doc_id}_{start_idx:05d}",
          text=chunk_text,
          kind="text",
          section=section,
          page=page,
          lang=_detect_lang(chunk_text),
          file_name=file_name,
          source_key=source_key,
        )
      )

    if end >= text_len:
      break
    start = max(end - CHUNK_OVERLAP, start + 1)

  return chunks


def blocks_to_chunks(
  blocks: list[Block],
  *,
  doc_id: str,
  file_name: str,
  source_key: str,
) -> list[ParsedChunk]:
  """Разбить блоки на ParsedChunk (таблицы — атомарные чанки)."""
  chunkable = [b for b in blocks if b.section != "references"]
  chunks: list[ParsedChunk] = []

  prev_paragraph: str | None = None
  for idx, block in enumerate(chunkable):
    if block.type == "table":
      context = prev_paragraph or ""
      text = f"{context}\n\n{block.text}".strip() if context else block.text
      chunks.append(
        ParsedChunk(
          doc_id=doc_id,
          chunk_id=f"{doc_id}_{idx:05d}",
          text=text,
          kind="table",
          section=block.section,
          page=block.page,
          lang=_detect_lang(block.text),
          file_name=file_name,
          source_key=source_key,
        )
      )
      prev_paragraph = None
      continue

    if block.type == "paragraph":
      prev_paragraph = block.text

  text_sections: dict[str, list[tuple[int, Block]]] = {}
  for idx, block in enumerate(chunkable):
    if block.type in ("paragraph", "heading"):
      text_sections.setdefault(block.section, []).append((idx, block))

  for section, indexed in text_sections.items():
    chunks.extend(
      _chunk_paragraphs(
        indexed,
        doc_id=doc_id,
        section=section,
        file_name=file_name,
        source_key=source_key,
      )
    )

  chunks.sort(key=lambda c: c.chunk_id)
  return chunks


def write_jsonl(chunks: list[ParsedChunk], out_path: Path) -> None:
  out_path.parent.mkdir(parents=True, exist_ok=True)
  with out_path.open("w", encoding="utf-8") as f:
    for chunk in chunks:
      f.write(chunk.model_dump_json() + "\n")
  logger.info("Wrote %d chunks to %s", len(chunks), out_path)


def write_references(reference_texts: list[str], out_path: Path) -> None:
  if not reference_texts:
    return
  out_path.parent.mkdir(parents=True, exist_ok=True)
  with out_path.open("w", encoding="utf-8") as f:
    json.dump(reference_texts, f, ensure_ascii=False, indent=2)
