"""
FastAPI Application Entry Point for the Smart Book Search Engine.
Provides RESTful APIs and serves the Vanilla JS/HTML/CSS demonstration interface.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.routes import router as api_router
from app.database import init_database
from app.search.engine import SearchEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("book_search")

static_dir = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown management.
    Initializes database and warms up in-memory search dictionary.
    """
    logger.info("Initializing Book Search Engine...")
    # Ensure database and seed data are ready
    conn = init_database(config.DATABASE_PATH, seed_data=True)

    # Initialize single shared SearchEngine instance
    engine = SearchEngine(conn)
    app.state.search_engine = engine
    logger.info("Search Engine instance warmed up successfully.")

    yield

    logger.info("Shutting down Search Engine...")
    engine.close()


app = FastAPI(
    title="Smart Book Search Engine",
    description=(
        "Production-ready deterministic search engine for books. "
        "No AI/LLM models. Multi-algorithm fuzzy matching, phonetic similarity, "
        "N-grams, FTS5 candidates, and business signals."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount endpoints at root level as specified by user requirements
app.include_router(api_router)
# Also include under /api prefix for conventional REST routing
app.include_router(api_router, prefix="/api")

# Mount static files directory
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serve the single-page HTML/CSS/Vanilla JS frontend demo."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Book Search API is running. Visit /docs for Swagger documentation."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
