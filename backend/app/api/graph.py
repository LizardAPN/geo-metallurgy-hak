"""GET /api/graph/subgraph — подграф для визуализации."""

import logging

from fastapi import APIRouter, Query

from app.api.mock_data import get_mock_subgraph
from app.schemas.api import SubgraphResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/graph/subgraph", response_model=SubgraphResponse)
def subgraph(
    node_ids: list[str] = Query(default=[]),
) -> SubgraphResponse:
    """
    Вернуть подграф для react-force-graph-2d.

    Args:
        node_ids: Опциональный список id узлов для фильтрации.
    """
    logger.info("subgraph node_ids=%s", node_ids)
    return get_mock_subgraph(node_ids if node_ids else None)
