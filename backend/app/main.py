"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import documents, graph, health, query
from app.config import settings
from app.graph.driver import close_driver
from app.retrieval.embedder import warmup as embedder_warmup

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Warming up embedding model...")
    try:
        await asyncio.to_thread(embedder_warmup)
        logger.info("Embedding model ready")
    except Exception:
        logger.exception("Embedding warmup failed; model will load lazily on first query")
    yield
    close_driver()


app = FastAPI(title="Научный клубок", version="0.1.0", lifespan=lifespan)

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
app.include_router(documents.router, prefix="/api", tags=["documents"])


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "Научный клубок", "status": "ok"}
