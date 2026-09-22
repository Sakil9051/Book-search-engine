"""
Pydantic data models for search request/response serialization.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    """Detailed score breakdown for search candidates when DEBUG_SEARCH is true."""
    exact_isbn: float = 0.0
    exact_title: float = 0.0
    exact_alias: float = 0.0
    exact_author: float = 0.0
    title_similarity: float = 0.0
    author_similarity: float = 0.0
    token_match: float = 0.0
    ngram_similarity: float = 0.0
    phonetic_similarity: float = 0.0
    popularity: float = 0.0
    sales: float = 0.0
    final_raw_score: float = 0.0


class SearchResult(BaseModel):
    """A single book item in the search results."""
    id: int
    title: str
    author: Optional[str] = None
    isbn: Optional[str] = None
    price: float
    stock: int
    similarity_score: float
    matched_fields: List[str]
    description: Optional[str] = None
    publisher: Optional[str] = None
    category: Optional[str] = None
    language: Optional[str] = "en"
    score_breakdown: Optional[ScoreBreakdown] = None


class SearchResponse(BaseModel):
    """Unified search response matching Section 21 specification."""
    query: str
    corrected_query: str
    correction_confidence: float
    correction_level: str  # 'HIGH', 'MEDIUM', 'LOW'
    did_you_mean: Optional[str] = None
    total_results: int = 0
    execution_time_ms: float = 0.0
    results: List[SearchResult] = Field(default_factory=list)


class AutocompleteItem(BaseModel):
    """A suggestion item for prefix/autocomplete searches."""
    id: int
    title: str
    author: Optional[str] = None
    type: str = "book"  # "book", "author", "alias"
    isbn: Optional[str] = None
    category: Optional[str] = None


class AutocompleteResponse(BaseModel):
    """Response structure for /autocomplete endpoint."""
    query: str
    results: List[AutocompleteItem] = Field(default_factory=list)


class BookDetail(BaseModel):
    """Full detail view for a specific book."""
    id: int
    title: str
    normalized_title: str
    author: Optional[str] = None
    normalized_author: Optional[str] = None
    isbn: Optional[str] = None
    description: Optional[str] = None
    publisher: Optional[str] = None
    category: Optional[str] = None
    language: Optional[str] = None
    price: float
    stock: int
    popularity_score: float
    sales_count: int
    aliases: List[str] = Field(default_factory=list)


class ClickLogRequest(BaseModel):
    """Payload for user click telemetry on search results."""
    query: str
    book_id: int


class ClickLogResponse(BaseModel):
    """Status response for search click registration."""
    success: bool
    message: str
