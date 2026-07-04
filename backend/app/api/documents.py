"""GET /api/documents/{doc_id}/link — presigned URL исходного документа."""

from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Path

from app.graph.driver import get_driver
from app.schemas.api import DocumentLinkResponse
from app.storage import get_storage

logger = logging.getLogger(__name__)
router = APIRouter()

DOC_ID_RE = re.compile(r"^doc_[0-9a-f]{12}$")

_LOOKUP_CYPHER = """
MATCH (p:Publication {doc_id: $doc_id})
RETURN p.source_path AS source_path, p.title AS title
"""


@router.get("/documents/{doc_id}/link", response_model=DocumentLinkResponse)
def document_link(
    doc_id: str = Path(..., pattern=r"^doc_[0-9a-f]{12}$"),
) -> DocumentLinkResponse:
    """Вернуть presigned URL исходного файла по doc_id публикации."""
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(status_code=422, detail="invalid doc_id")

    storage = get_storage()
    if not storage.available:
        raise HTTPException(status_code=503, detail="хранилище документов недоступно")

    driver = get_driver()
    with driver.session() as session:
        row = session.run(_LOOKUP_CYPHER, doc_id=doc_id).single()

    if row is None:
        raise HTTPException(status_code=404, detail="publication not found")

    source_path = row.get("source_path")
    title = row.get("title") or ""
    if not source_path or not str(source_path).strip():
        raise HTTPException(status_code=404, detail="publication not found")

    source_key = str(source_path)
    file_name = PurePosixPath(source_key).name
    url = storage.presigned_url(source_key)
    logger.info("document link: doc_id=%s file_name=%s", doc_id, file_name)

    return DocumentLinkResponse(url=url, title=str(title), file_name=file_name)
