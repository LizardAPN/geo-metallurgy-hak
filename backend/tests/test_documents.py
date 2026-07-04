"""Тесты GET /api/documents/{doc_id}/link."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api import documents as documents_api
from app.main import app

client = TestClient(app)

VALID_DOC_ID = "doc_7d11e81f33f5"


def _mock_storage(*, available: bool = True, url: str = "https://s3.example/signed") -> MagicMock:
    storage = MagicMock()
    storage.available = available
    storage.presigned_url.return_value = url
    return storage


def _mock_driver_row(source_path: str | None, title: str = "Test doc") -> MagicMock:
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    if source_path is None:
        session.run.return_value.single.return_value = None
    else:
        row = {"source_path": source_path, "title": title}
        session.run.return_value.single.return_value = row

    return driver


def test_document_link_invalid_doc_id() -> None:
    response = client.get("/api/documents/doc_invalid/link")
    assert response.status_code == 422


def test_document_link_storage_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents_api, "get_storage", lambda: _mock_storage(available=False))

    response = client.get(f"/api/documents/{VALID_DOC_ID}/link")
    assert response.status_code == 503
    assert response.json()["detail"] == "хранилище документов недоступно"


def test_document_link_publication_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents_api, "get_storage", lambda: _mock_storage())
    monkeypatch.setattr(documents_api, "get_driver", lambda: _mock_driver_row(None))

    response = client.get(f"/api/documents/{VALID_DOC_ID}/link")
    assert response.status_code == 404


def test_document_link_empty_source_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents_api, "get_storage", lambda: _mock_storage())
    monkeypatch.setattr(documents_api, "get_driver", lambda: _mock_driver_row(""))

    response = client.get(f"/api/documents/{VALID_DOC_ID}/link")
    assert response.status_code == 404


def test_document_link_success(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _mock_storage(url="https://s3.example/signed?sig=abc")
    monkeypatch.setattr(documents_api, "get_storage", lambda: storage)
    monkeypatch.setattr(
        documents_api,
        "get_driver",
        lambda: _mock_driver_row("raw/ЦМ № 09-2017.pdf", title="ЦМ № 09-2017"),
    )

    response = client.get(f"/api/documents/{VALID_DOC_ID}/link")
    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "https://s3.example/signed?sig=abc"
    assert data["title"] == "ЦМ № 09-2017"
    assert data["file_name"] == "ЦМ № 09-2017.pdf"
    storage.presigned_url.assert_called_once_with("raw/ЦМ № 09-2017.pdf")
