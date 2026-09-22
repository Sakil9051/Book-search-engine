"""
Core Search Engine implementation.
Completely standalone and independent of any web framework (FastAPI, Express, etc.).
Can be imported directly into scripts, CLI tools, or background workers.
"""

import collections
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from app import config
from app.database import get_db_connection
from app.models.book import (
    AutocompleteItem,
    AutocompleteResponse,
    BookDetail,
    SearchResponse,
    SearchResult,
)
from app.search.autocomplete import AutocompleteEngine
from app.search.dictionary import DictionaryManager
from app.search.fuzzy import FuzzyMatcher
from app.search.history import SearchHistoryManager
from app.search.normalizer import TextNormalizer
from app.search.ranking import RankingEngine
from app.search.spelling import SpellingCorrector
from app.search.tokenizer import Tokenizer
from app.search.typo import TypoDictionary

# Backward-compatible alias
SpellCorrector = SpellingCorrector

logger = logging.getLogger(__name__)


class SearchEngine:
    """
    Production-ready deterministic book search engine.
    Orchestrates exact matching, spell correction, FTS5 candidate generation,
    fuzzy multi-metric ranking, and search query telemetry.
    """

    def __init__(self, db: Optional[Union[sqlite3.Connection, str, Path]] = None):
        """
        Initialize the search engine with a SQLite connection or file path.
        If db is None, uses default path from app.config.
        """
        if isinstance(db, sqlite3.Connection):
            self.conn = db
            self._owns_conn = False
        elif isinstance(db, (str, Path)):
            self.conn = get_db_connection(Path(db))
            self._owns_conn = True
        else:
            self.conn = get_db_connection(config.DATABASE_PATH)
            self._owns_conn = True

        # In-memory dictionary, typo dict, and spelling corrector
        self.dict_manager = DictionaryManager(self.conn)
        self.dict_manager.ensure_loaded(self.conn)
        self.typo_dict = TypoDictionary(self.conn)
        self.typo_dict.ensure_loaded(self.conn)
        self.corrector = SpellingCorrector(self.dict_manager, self.conn, self.typo_dict)
        self.autocomplete_engine = AutocompleteEngine(self.conn, self.corrector)
        self.history_manager = SearchHistoryManager(self.conn, self.typo_dict)

        # In-memory LRU query cache: normalized_query -> SearchResponse
        self._lru_cache: collections.OrderedDict = collections.OrderedDict()
        self._cache_size = config.SEARCH_CACHE_SIZE

    def _get_connection(self) -> sqlite3.Connection:
        """Ensure connection is healthy."""
        return self.conn

    def _generate_candidates(
        self,
        norm_query: str,
        norm_corrected: str,
        clean_isbn: Optional[str],
        limit: int = config.CANDIDATE_POOL_LIMIT,
    ) -> List[dict]:
        """
        Efficient candidate retrieval using SQLite indexes, FTS5, and prefix lookups.
        Prevents full table scans and expensive fuzzy calculations across irrelevant rows.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        candidate_ids: Set[int] = set()

        # 1. Exact ISBN check
        if clean_isbn:
            cursor.execute("SELECT id FROM books WHERE isbn = ? LIMIT 5", (clean_isbn,))
            for (bid,) in cursor.fetchall():
                candidate_ids.add(bid)

        # 2. Exact Title check
        cursor.execute("SELECT id FROM books WHERE normalized_title = ? LIMIT 5", (norm_query,))
        for (bid,) in cursor.fetchall():
            candidate_ids.add(bid)

        if norm_corrected and norm_corrected != norm_query:
            cursor.execute("SELECT id FROM books WHERE normalized_title = ? LIMIT 5", (norm_corrected,))
            for (bid,) in cursor.fetchall():
                candidate_ids.add(bid)

        # 3. Exact Alias check
        cursor.execute(
            "SELECT book_id FROM book_aliases WHERE normalized_alias IN (?, ?) LIMIT 10",
            (norm_query, norm_corrected),
        )
        for (bid,) in cursor.fetchall():
            candidate_ids.add(bid)

        # 4. FTS5 full-text candidate retrieval
        # Build sanitized MATCH query from tokens
        query_tokens = Tokenizer.tokenize(norm_corrected or norm_query)
        sig_tokens = Tokenizer.filter_stop_words(query_tokens) or query_tokens

        if sig_tokens:
            # Match using prefix wildcard per token in FTS5
            fts_query = " OR ".join(f'"{t}"*' for t in sig_tokens)
            try:
                cursor.execute(
                    "SELECT rowid FROM books_fts WHERE books_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_query, limit // 2),
                )
                for (rowid,) in cursor.fetchall():
                    candidate_ids.add(rowid)
            except sqlite3.OperationalError as e:
                logger.debug("FTS5 query failed or unsupported syntax: %s", e)

        # 5. Partial/Prefix LIKE queries on title and author
        prefix_pattern = f"{norm_query[:6]}%" if len(norm_query) >= 3 else f"{norm_query}%"
        cursor.execute(
            """
            SELECT id FROM books
            WHERE normalized_title LIKE ?
               OR normalized_author LIKE ?
            ORDER BY popularity_score DESC LIMIT ?
            """,
            (prefix_pattern, prefix_pattern, limit // 2),
        )
        for (bid,) in cursor.fetchall():
            candidate_ids.add(bid)

        # Also search individual significant tokens with LIKE
        for t in sig_tokens:
            if len(t) >= 4:
                cursor.execute(
                    """
                    SELECT id FROM books
                    WHERE normalized_title LIKE ?
                       OR normalized_author LIKE ?
                    LIMIT 15
                    """,
                    (f"%{t}%", f"%{t}%"),
                )
                for (bid,) in cursor.fetchall():
                    candidate_ids.add(bid)

        # 6. Alias LIKE matches
        cursor.execute(
            "SELECT book_id FROM book_aliases WHERE normalized_alias LIKE ? LIMIT 15",
            (f"%{norm_query}%",),
        )
        for (bid,) in cursor.fetchall():
            candidate_ids.add(bid)

        # 7. Fallback: If candidate count is low, add top popular books to pool
        if len(candidate_ids) < 10:
            cursor.execute(
                "SELECT id FROM books ORDER BY popularity_score DESC LIMIT ?",
                (15 - len(candidate_ids),),
            )
            for (bid,) in cursor.fetchall():
                candidate_ids.add(bid)

        if not candidate_ids:
            return []

        # Load full records and aliases for all gathered candidates in one query
        placeholders = ",".join("?" for _ in candidate_ids)
        cursor.execute(
            f"""
            SELECT id, title, normalized_title, author, normalized_author,
                   isbn, description, publisher, category, language, price, stock,
                   popularity_score, sales_count
            FROM books
            WHERE id IN ({placeholders})
            """,
            list(candidate_ids),
        )
        rows = cursor.fetchall()

        # Load aliases for these candidates
        cursor.execute(
            f"SELECT book_id, alias FROM book_aliases WHERE book_id IN ({placeholders})",
            list(candidate_ids),
        )
        alias_map: Dict[int, List[str]] = {}
        for b_id, alias in cursor.fetchall():
            alias_map.setdefault(b_id, []).append(alias)

        candidates = []
        for r in rows:
            book_dict = dict(r)
            book_dict["aliases"] = alias_map.get(book_dict["id"], [])
            candidates.append(book_dict)

        return candidates

    def search(
        self,
        query: str,
        limit: int = config.DEFAULT_SEARCH_LIMIT,
        debug: bool = config.DEBUG_SEARCH,
    ) -> SearchResponse:
        """
        Execute the full search pipeline:
        1. Validate query & check LRU cache
        2. Normalize & detect ISBN
        3. Spelling correction & confidence scoring
        4. FTS5 / index candidate generation
        5. Fuzzy, phonetic, n-gram, and token similarity evaluation
        6. Ranking & score normalization
        7. Log search telemetry & cache result
        """
        start_time = time.perf_counter()

        clean_query = query.strip()[: config.MAX_QUERY_LENGTH]
        if not clean_query:
            return SearchResponse(
                query="",
                corrected_query="",
                correction_confidence=100.0,
                correction_level="HIGH",
                did_you_mean=None,
                total_results=0,
                execution_time_ms=0.0,
                results=[],
            )

        norm_query = TextNormalizer.normalize(clean_query)
        cache_key = f"{norm_query}:{limit}:{debug}"

        # Check in-memory LRU cache
        if cache_key in self._lru_cache:
            cached_resp = self._lru_cache[cache_key]
            # Move to end (most recently accessed)
            self._lru_cache.move_to_end(cache_key)
            return cached_resp

        # Step 1: Detect ISBN
        clean_isbn = TextNormalizer.clean_isbn(clean_query)

        # Step 2: Spell correction
        corrected_query, confidence, level, did_you_mean = self.corrector.correct_query(
            clean_query, self.conn
        )

        # If confidence is LOW, do not automatically replace the search terms
        effective_query = corrected_query if level in ("HIGH", "MEDIUM") else norm_query

        # Step 3: Candidate Generation
        candidates = self._generate_candidates(
            norm_query=norm_query,
            norm_corrected=effective_query,
            clean_isbn=clean_isbn,
        )

        # Step 4 & 5: Score and Rank Candidates
        scored_results: List[Tuple[float, SearchResult]] = []
        for cand in candidates:
            raw_score, sim_percent, matched_fields, breakdown = RankingEngine.score_candidate(
                candidate=cand,
                query=norm_query,
                corrected_query=effective_query,
                debug=debug,
            )

            # Filter out completely irrelevant items (e.g. sim_percent < 25 unless query is very short)
            if raw_score > 0:
                item = SearchResult(
                    id=cand["id"],
                    title=cand["title"],
                    author=cand["author"],
                    isbn=cand["isbn"],
                    price=float(cand["price"]),
                    stock=int(cand["stock"]),
                    similarity_score=sim_percent,
                    matched_fields=matched_fields,
                    description=cand["description"],
                    publisher=cand["publisher"],
                    category=cand["category"],
                    language=cand.get("language", "en"),
                    score_breakdown=breakdown,
                )
                scored_results.append((raw_score, item))

        # Sort descending by raw score
        scored_results.sort(key=lambda x: x[0], reverse=True)

        results = [item for _, item in scored_results[: max(1, min(limit, config.MAX_SEARCH_LIMIT))]]
        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        # Prepare Did You Mean title:
        # Show "Did you mean: [Book Title]?" if level is MEDIUM or if did_you_mean title is found
        # but the top result wasn't an exact title match
        dym_text = None
        if level in ("HIGH", "MEDIUM") and did_you_mean:
            dym_text = did_you_mean
        elif results and results[0].similarity_score >= 85.0 and results[0].title.lower() != clean_query.lower():
            if level == "MEDIUM" or (norm_query != TextNormalizer.normalize(results[0].title)):
                dym_text = results[0].title

        correction_applied = (level == "HIGH" and effective_query != norm_query)

        response = SearchResponse(
            original_query=clean_query,
            query=clean_query,
            corrected_query=effective_query,
            correction_applied=correction_applied,
            correction_confidence=confidence,
            confidence=confidence,
            correction_level=level,
            did_you_mean=dym_text,
            suggestion=dym_text,
            total_results=len(results),
            execution_time_ms=elapsed_ms,
            results=results,
        )

        # Step 6: Log Search Telemetry via SearchHistoryManager
        self.history_manager.log_search(
            query=clean_query,
            normalized_query=norm_query,
            corrected_query=effective_query,
            result_count=len(results),
            conn=self.conn,
        )

        # Store in LRU cache
        if len(self._lru_cache) >= self._cache_size:
            self._lru_cache.popitem(last=False)
        self._lru_cache[cache_key] = response

        return response

    def autocomplete(
        self, prefix: str, limit: int = config.AUTOCOMPLETE_LIMIT
    ) -> AutocompleteResponse:
        """
        High-performance prefix & typo-tolerant autocomplete system.
        Searches book titles, authors, aliases, categories, and publishers.
        """
        return self.autocomplete_engine.autocomplete(prefix=prefix, limit=limit, conn=self.conn)

    def get_book(self, book_id: int) -> Optional[BookDetail]:
        """Fetch complete details for a single book by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM books WHERE id = ?", (book_id,))
        row = cursor.fetchone()
        if not row:
            return None

        # Fetch aliases
        cursor.execute("SELECT alias FROM book_aliases WHERE book_id = ?", (book_id,))
        aliases = [r[0] for r in cursor.fetchall()]

        return BookDetail(
            id=row["id"],
            title=row["title"],
            normalized_title=row["normalized_title"],
            author=row["author"],
            normalized_author=row["normalized_author"],
            isbn=row["isbn"],
            description=row["description"],
            publisher=row["publisher"],
            category=row["category"],
            language=row["language"],
            price=float(row["price"]),
            stock=int(row["stock"]),
            popularity_score=float(row["popularity_score"]),
            sales_count=int(row["sales_count"]),
            aliases=aliases,
        )

    def log_click(self, query: str, book_id: int) -> bool:
        """
        Record a user click on a search result.
        Enforces search history learning: if users frequently click a book for a query,
        reinforces the association as a high-confidence alias and learns typos.
        """
        return self.history_manager.log_click(query=query, book_id=book_id, conn=self.conn)

    def close(self) -> None:
        """Close database connection if owned."""
        if self._owns_conn and self.conn:
            self.conn.close()
