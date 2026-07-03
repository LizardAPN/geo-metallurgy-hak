"""E2E smoke tests на 4 эталонных запроса из DEMO.md."""

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.api import QueryResponse

client = TestClient(app)

# TODO: заменить на дословные формулировки с платформы хакатона
REFERENCE_QUERIES = [
  # 1. Числовые диапазоны (обессоливание, сульфаты, сухой остаток)
    "Какие методы обессоливания воды применялись при содержании сульфатов 200–300 мг/л "
    "и сухом остатке ≤ 1000 мг/дм³? Приведи источники и условия.",
    # 2. Эксперименты по процессу с фильтрами гео+год
    "Найди эксперименты по кучному выщелачиванию никелевых руд в России после 2015 года.",
    # 3. Материал → свойства → режимы, противоречия
    "Какие режимы обработки влияют на извлечение меди при флотации? "
    "Где источники противоречат друг другу?",
    # 4. Эксперты
    "Кто в компании / в литературе занимался очисткой сточных вод от сульфатов? "
    "Какие у них публикации?",
]


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["neo4j"] in ("ok", "unavailable")


def test_query_reference_queries() -> None:
    for query_text in REFERENCE_QUERIES:
        response = client.post("/api/query", json={"query": query_text})
        assert response.status_code == 200, f"Failed for: {query_text[:60]}"
        result = QueryResponse.model_validate(response.json())
        assert result.answer_markdown.strip(), "answer_markdown must not be empty"
        assert result.mock is True, "Scaffold stage: expect mock response"
        assert result.citations, "citations must not be empty"
        assert result.graph_subset.nodes, "graph_subset must have nodes"


def test_subgraph() -> None:
    response = client.get("/api/graph/subgraph")
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) > 0
    assert data["mock"] is True
