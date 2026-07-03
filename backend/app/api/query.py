"""POST /api/query — главный эндпоинт поисково-аналитической системы."""

import logging

from fastapi import APIRouter

from app.api.mock_data import get_mock_query_response
from app.schemas.api import GraphSubset, QueryRequest, QueryResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _run_pipeline(request: QueryRequest) -> QueryResponse | None:
    """
    Попытка реального pipeline: retrieval → synthesis.

    Returns:
        QueryResponse при успехе или None если модули не готовы.
    """
    try:
        from app.retrieval.hybrid import hybrid_retrieve
        from app.synthesis.answerer import synthesize_answer
        from app.synthesis.gaps import detect_gaps

        # Stubs raise NotImplementedError until implemented
        context = hybrid_retrieve([], [], top_k=20)
        answer_md, citations = synthesize_answer(request.query, context)
        gaps = detect_gaps(context)
        return QueryResponse(
            answer_markdown=answer_md,
            citations=citations,
            graph_subset=GraphSubset(nodes=context.nodes, edges=context.edges),
            knowledge_gaps=gaps,
            mock=False,
        )
    except NotImplementedError:
        logger.debug("Pipeline not ready, falling back to mock")
        return None
    except Exception as exc:
        logger.warning("Pipeline error: %s", exc)
        return None


@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    """
    Обработать запрос пользователя.

    Всегда возвращает валидный QueryResponse.
    При недоступном pipeline — мок с warning-флагом.
    """
    logger.info("query: %r", request.query[:120])

    result = _run_pipeline(request)
    if result is not None:
        return result

    mock = get_mock_query_response()
    mock.warning = (
        "Ответ на мок-данных. Pipeline retrieval/synthesis ещё не подключён."
    )
    return mock
