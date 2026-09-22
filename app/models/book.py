"""
Pydantic data models for search request/response serialization.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, model_validator


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
    """Unified search response matching Section 6 & 19 specification."""
    original_query: str
    query: Optional[str] = None
    corrected_query: str
    correction_applied: bool = False
    correction_confidence: float = 0.0
    confidence: Optional[float] = None
    correction_level: str = "LOW"  # 'HIGH', 'MEDIUM', 'LOW'
    did_you_mean: Optional[str] = None
    suggestion: Optional[str] = None
    total_results: int = 0
    execution_time_ms: float = 0.0
    results: List[SearchResult] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def sync_query_fields(cls, data: Any):
        if isinstance(data, dict):
            if "original_query" in data and "query" not in data:
                data["query"] = data["original_query"]
            elif "query" in data and "original_query" not in data:
                data["original_query"] = data["query"]
            if "correction_confidence" in data and "confidence" not in data:
                data["confidence"] = data["correction_confidence"]
            elif "confidence" in data and "correction_confidence" not in data:
                data["correction_confidence"] = data["confidence"]
            if "did_you_mean" in data and "suggestion" not in data:
                data["suggestion"] = data["did_you_mean"]
            elif "suggestion" in data and "did_you_mean" not in data:
                data["did_you_mean"] = data["suggestion"]
        return data


class AutocompleteItem(BaseModel):
    """A suggestion item for prefix/autocomplete searches."""
    type: str = "book"  # "book", "author", "alias", "category", "publisher"
    id: Optional[int] = None
    title: str
    text: Optional[str] = None
    author: Optional[str] = None
    match: Optional[str] = None
    isbn: Optional[str] = None
    category: Optional[str] = None
    publisher: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def sync_text_and_title(cls, data: Any):
        if isinstance(data, dict):
            if "text" in data and "title" not in data:
                data["title"] = data["text"]
            elif "title" in data and "text" not in data:
                data["text"] = data["title"]
        return data


class AutocompleteResponse(BaseModel):
    """Response structure for /autocomplete endpoint matching Section 18."""
    query: str
    corrected_query: Optional[str] = None
    correction_confidence: Optional[float] = None
    did_you_mean: Optional[str] = None
    suggestions: List[AutocompleteItem] = Field(default_factory=list)
    results: List[AutocompleteItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def sync_suggestions_and_results(cls, data: Any):
        if isinstance(data, dict):
            if "suggestions" in data and "results" not in data:
                data["results"] = data["suggestions"]
            elif "results" in data and "suggestions" not in data:
                data["suggestions"] = data["results"]
        return data


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
