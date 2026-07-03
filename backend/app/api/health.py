"""Health check endpoint."""

import logging

from fastapi import APIRouter
from neo4j import GraphDatabase

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_neo4j() -> str:
    try:
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        driver.verify_connectivity()
        driver.close()
        return "ok"
    except Exception as exc:
        logger.warning("Neo4j unavailable: %s", exc)
        return "unavailable"


@router.get("/health")
def health() -> dict[str, str]:
    """Проверка состояния сервиса и Neo4j."""
    return {
        "status": "ok",
        "neo4j": _check_neo4j(),
    }
