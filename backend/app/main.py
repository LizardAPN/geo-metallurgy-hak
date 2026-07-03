"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import graph, health, query
from app.config import settings

app = FastAPI(title="Научный клубок", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(query.router, prefix="/api", tags=["query"])
app.include_router(graph.router, prefix="/api", tags=["graph"])


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "Научный клубок", "status": "ok"}
