"""
FastAPI route handlers for Book Search Engine endpoints.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pathlib import Path

from app import config
from app.models.book import (
    AutocompleteResponse,
    BookDetail,
    ClickLogRequest,
    SearchResponse,
)
from app.search.engine import SearchEngine

router = APIRouter()

# Engine reference will be attached to app.state in main.py
def get_engine(request: Request) -> SearchEngine:
    return request.app.state.search_engine


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "BookSearchEngine"}


@router.get("/search", response_model=SearchResponse, summary="Smart Book Search")
async def search_books(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = Query(config.DEFAULT_SEARCH_LIMIT, ge=1, le=config.MAX_SEARCH_LIMIT, description="Max results"),
    debug: bool = Query(False, description="Include detailed scoring breakdown"),
):
    """
    Execute full smart search pipeline:
    - Deterministic text normalization
    - ISBN detection
    - Word-level spell correction & confidence classification
    - Candidate generation via FTS5
    - Multi-algorithm ranking (Levenshtein, Jaro-Winkler, N-grams, Phonetics, Sales, Popularity)
    """
    engine = get_engine(request)
    return engine.search(query=q, limit=limit, debug=debug)


@router.get("/autocomplete", response_model=AutocompleteResponse, summary="Search Autocomplete / Prefix")
async def autocomplete(
    request: Request,
    q: str = Query(..., min_length=1, description="Prefix or partial query"),
    limit: int = Query(config.AUTOCOMPLETE_LIMIT, ge=1, le=20, description="Max autocomplete items"),
):
    """
    Fast autocomplete returning matching book titles, authors, and aliases.
    """
    engine = get_engine(request)
    return engine.autocomplete(prefix=q, limit=limit)


@router.get("/books/{book_id}", response_model=BookDetail, summary="Get Book Details")
async def get_book_detail(request: Request, book_id: int):
    """
    Retrieve single book record including all aliases, stock, price, and publisher details.
    """
    engine = get_engine(request)
    book = engine.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail=f"Book with ID {book_id} not found")
    return book


@router.post("/search/click", summary="Log User Click for Search History Learning")
async def log_click(request: Request, payload: ClickLogRequest):
    """
    Register a user click on a book result for a search query.
    Reinforces high-frequency corrections deterministically in search_logs and book_aliases.
    """
    engine = get_engine(request)
    success = engine.log_click(payload.query, payload.book_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to record click")
    return {"status": "success", "message": "Click registered", "query": payload.query, "book_id": payload.book_id}


@router.get("/stats", summary="Engine and Database Telemetry")
async def get_stats(request: Request):
    """
    Retrieve real-time statistics: total books, vocabulary size, logged queries, and active aliases.
    """
    engine = get_engine(request)
    conn = engine._get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM books")
    book_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM search_dictionary")
    dict_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM book_aliases")
    alias_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM search_logs")
    log_count = cursor.fetchone()[0]

    cursor.execute("SELECT query, result_count, created_at FROM search_logs ORDER BY created_at DESC LIMIT 5")
    recent_logs = [dict(r) for r in cursor.fetchall()]

    return {
        "status": "healthy",
        "total_books": book_count,
        "vocabulary_entries": dict_count,
        "total_aliases": alias_count,
        "queries_logged": log_count,
        "cache_entries": len(engine._lru_cache),
        "recent_queries": recent_logs,
    }
