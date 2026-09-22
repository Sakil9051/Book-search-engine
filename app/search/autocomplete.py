"""
High-performance, typo-tolerant AutocompleteEngine.
Uses indexed SQLite column prefix matching, FTS5 candidate generation,
LRU caching, deterministic spelling correction, and fuzzy matching fallback.
Searches: Book title, Author, Alias, Category, Publisher.
"""

from collections import OrderedDict
import logging
import sqlite3
from typing import Dict, List, Optional, Set, Tuple
from app import config
from app.models.book import AutocompleteItem, AutocompleteResponse
from app.search.fuzzy import FuzzyMatcher
from app.search.normalizer import TextNormalizer
from app.search.spelling import SpellingCorrector
from app.search.tokenizer import Tokenizer

logger = logging.getLogger(__name__)


class AutocompleteEngine:
    """
    Dedicated autocomplete engine executing sub-millisecond prefix searches.
    """

    def __init__(
        self,
        db_conn: Optional[sqlite3.Connection] = None,
        spelling_corrector: Optional[SpellingCorrector] = None,
    ):
        self.db_conn = db_conn
        self.spelling_corrector = spelling_corrector
        # In-memory LRU cache for frequent autocomplete queries: query -> AutocompleteResponse
        self._cache: OrderedDict[str, AutocompleteResponse] = OrderedDict()
        self._max_cache_size = config.AUTOCOMPLETE_CACHE_SIZE

    def autocomplete(
        self,
        prefix: str,
        limit: int = 10,
        conn: Optional[sqlite3.Connection] = None,
    ) -> AutocompleteResponse:
        """
        Fast, typo-tolerant autocomplete starting after 2 characters.
        Searches: Title, Author, Alias, Category, Publisher.
        """
        norm_prefix = TextNormalizer.normalize(prefix)
        # 1. Require at least 2 characters
        if len(norm_prefix) < 2:
            return AutocompleteResponse(query=prefix, suggestions=[])

        # 2. Check LRU Cache
        cache_key = f"{norm_prefix}_{limit}"
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            cached_res = self._cache[cache_key]
            return cached_res

        target_conn = conn or self.db_conn
        if not target_conn:
            return AutocompleteResponse(query=prefix, suggestions=[])

        max_suggestions = min(limit, config.AUTOCOMPLETE_LIMIT)
        seen_keys: Set[str] = set()
        suggestions: List[AutocompleteItem] = []

        # 3. Stage 1: Exact Indexed Prefix Matching on Books (Title, Author, Category, Publisher)
        self._search_indexed_prefixes(target_conn, norm_prefix, max_suggestions, seen_keys, suggestions)

        # 4. Stage 2: Indexed Book Aliases Prefix Matching
        if len(suggestions) < max_suggestions:
            self._search_alias_prefixes(target_conn, norm_prefix, max_suggestions, seen_keys, suggestions)

        # 5. Stage 3: SQLite FTS5 Prefix Candidate Generation
        if len(suggestions) < max_suggestions:
            self._search_fts5_prefixes(target_conn, norm_prefix, max_suggestions, seen_keys, suggestions)

        # 6. Stage 4: Typo-Tolerant Autocomplete (if results are sparse or typo detected)
        corrected_query: Optional[str] = None
        correction_conf: Optional[float] = None
        did_you_mean: Optional[str] = None

        if len(suggestions) < min(3, max_suggestions) and self.spelling_corrector:
            # Check if prefix has spelling mistakes (e.g., 'hary pot' -> 'harry potter', 'atomc hab' -> 'atomic habits')
            corr_q, conf, level, dym = self.spelling_corrector.correct_query(norm_prefix, target_conn)
            if corr_q and corr_q != norm_prefix and conf >= config.CONFIDENCE_MEDIUM:
                corrected_query = corr_q
                correction_conf = conf
                did_you_mean = dym

                # Search using the corrected prefix
                self._search_indexed_prefixes(target_conn, corr_q, max_suggestions, seen_keys, suggestions)
                if len(suggestions) < max_suggestions:
                    self._search_alias_prefixes(target_conn, corr_q, max_suggestions, seen_keys, suggestions)
                if len(suggestions) < max_suggestions:
                    self._search_fts5_prefixes(target_conn, corr_q, max_suggestions, seen_keys, suggestions)

        # 7. Stage 5: Fallback to Fuzzy Prefix Matching ONLY when not enough results
        if len(suggestions) < min(3, max_suggestions):
            self._search_fuzzy_candidates(target_conn, norm_prefix, max_suggestions, seen_keys, suggestions)

        final_suggestions = suggestions[:max_suggestions]

        response = AutocompleteResponse(
            query=prefix,
            corrected_query=corrected_query,
            correction_confidence=correction_conf,
            did_you_mean=did_you_mean,
            suggestions=final_suggestions,
        )

        # Store in LRU cache
        if len(self._cache) >= self._max_cache_size:
            self._cache.popitem(last=False)
        self._cache[cache_key] = response

        return response

    def _search_indexed_prefixes(
        self,
        conn: sqlite3.Connection,
        norm_prefix: str,
        limit: int,
        seen_keys: Set[str],
        suggestions: List[AutocompleteItem],
    ) -> None:
        """Search books title, author, category, publisher via indexes."""
        cursor = conn.cursor()
        prefix_pattern = f"{norm_prefix}%"

        # Titles starting with prefix
        cursor.execute(
            """
            SELECT id, title, author, isbn, category, publisher
            FROM books
            WHERE normalized_title LIKE ?
            ORDER BY popularity_score DESC, sales_count DESC
            LIMIT ?
            """,
            (prefix_pattern, limit),
        )
        for row in cursor.fetchall():
            key = f"book_{row['id']}"
            if key not in seen_keys:
                seen_keys.add(key)
                suggestions.append(
                    AutocompleteItem(
                        type="book",
                        id=row["id"],
                        title=row["title"],
                        author=row["author"],
                        match=norm_prefix,
                        isbn=row["isbn"],
                        category=row["category"],
                        publisher=row["publisher"],
                    )
                )
                if len(suggestions) >= limit:
                    return

        # Authors starting with prefix
        cursor.execute(
            """
            SELECT DISTINCT id, author, category, publisher
            FROM books
            WHERE normalized_author LIKE ?
            ORDER BY popularity_score DESC
            LIMIT ?
            """,
            (prefix_pattern, limit - len(suggestions)),
        )
        for row in cursor.fetchall():
            key = f"author_{row['author']}"
            if key not in seen_keys and row["author"]:
                seen_keys.add(key)
                suggestions.append(
                    AutocompleteItem(
                        type="author",
                        id=row["id"],
                        title=row["author"],
                        author=row["author"],
                        match=norm_prefix,
                        category=row["category"],
                        publisher=row["publisher"],
                    )
                )
                if len(suggestions) >= limit:
                    return

        # Categories starting with prefix
        cursor.execute(
            """
            SELECT DISTINCT category
            FROM books
            WHERE category IS NOT NULL AND LOWER(category) LIKE ?
            LIMIT ?
            """,
            (prefix_pattern, limit - len(suggestions)),
        )
        for row in cursor.fetchall():
            cat = row[0]
            if cat:
                key = f"category_{cat.lower()}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    suggestions.append(
                        AutocompleteItem(
                            type="category",
                            id=None,
                            title=cat,
                            match=norm_prefix,
                            category=cat,
                        )
                    )
                    if len(suggestions) >= limit:
                        return

        # Publishers starting with prefix
        cursor.execute(
            """
            SELECT DISTINCT publisher
            FROM books
            WHERE publisher IS NOT NULL AND LOWER(publisher) LIKE ?
            LIMIT ?
            """,
            (prefix_pattern, limit - len(suggestions)),
        )
        for row in cursor.fetchall():
            pub = row[0]
            if pub:
                key = f"publisher_{pub.lower()}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    suggestions.append(
                        AutocompleteItem(
                            type="publisher",
                            id=None,
                            title=pub,
                            match=norm_prefix,
                            publisher=pub,
                        )
                    )
                    if len(suggestions) >= limit:
                        return

    def _search_alias_prefixes(
        self,
        conn: sqlite3.Connection,
        norm_prefix: str,
        limit: int,
        seen_keys: Set[str],
        suggestions: List[AutocompleteItem],
    ) -> None:
        """Search book aliases starting with prefix."""
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.alias, b.id, b.title, b.author, b.isbn, b.category, b.publisher
            FROM book_aliases a
            JOIN books b ON b.id = a.book_id
            WHERE a.normalized_alias LIKE ?
            ORDER BY a.confidence DESC, b.popularity_score DESC
            LIMIT ?
            """,
            (f"{norm_prefix}%", limit - len(suggestions)),
        )
        for row in cursor.fetchall():
            key = f"book_{row['id']}"
            if key not in seen_keys:
                seen_keys.add(key)
                suggestions.append(
                    AutocompleteItem(
                        type="book",
                        id=row["id"],
                        title=row["title"],
                        author=row["author"],
                        match=norm_prefix,
                        isbn=row["isbn"],
                        category=row["category"],
                        publisher=row["publisher"],
                    )
                )
                if len(suggestions) >= limit:
                    return

    def _search_fts5_prefixes(
        self,
        conn: sqlite3.Connection,
        norm_prefix: str,
        limit: int,
        seen_keys: Set[str],
        suggestions: List[AutocompleteItem],
    ) -> None:
        """Use FTS5 prefix query to find words within titles and authors."""
        clean_prefix = "".join(c for c in norm_prefix if c.isalnum() or c.isspace()).strip()
        if not clean_prefix:
            return

        fts_query = f"{clean_prefix}*"
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT b.id, b.title, b.author, b.isbn, b.category, b.publisher
                FROM books_fts f
                JOIN books b ON b.id = f.rowid
                WHERE books_fts MATCH ?
                ORDER BY b.popularity_score DESC
                LIMIT ?
                """,
                (fts_query, limit - len(suggestions)),
            )
            for row in cursor.fetchall():
                key = f"book_{row['id']}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    suggestions.append(
                        AutocompleteItem(
                            type="book",
                            id=row["id"],
                            title=row["title"],
                            author=row["author"],
                            match=norm_prefix,
                            isbn=row["isbn"],
                            category=row["category"],
                            publisher=row["publisher"],
                        )
                    )
                    if len(suggestions) >= limit:
                        return
        except sqlite3.OperationalError:
            pass

    def _search_fuzzy_candidates(
        self,
        conn: sqlite3.Connection,
        norm_prefix: str,
        limit: int,
        seen_keys: Set[str],
        suggestions: List[AutocompleteItem],
    ) -> None:
        """
        Fuzzy comparison fallback: Only scans top 60 popular books to avoid slow full table scans.
        """
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, normalized_title, author, normalized_author, isbn, category, publisher
            FROM books
            ORDER BY popularity_score DESC
            LIMIT 60
            """
        )
        popular_books = cursor.fetchall()
        fuzzy_matches: List[Tuple[float, sqlite3.Row]] = []

        for row in popular_books:
            key = f"book_{row['id']}"
            if key in seen_keys:
                continue

            sim_title = FuzzyMatcher.jaro_winkler_similarity(norm_prefix, row["normalized_title"][: len(norm_prefix) + 3])
            sim_auth = (
                FuzzyMatcher.jaro_winkler_similarity(norm_prefix, (row["normalized_author"] or "")[: len(norm_prefix) + 3])
                if row["normalized_author"]
                else 0.0
            )
            best_sim = max(sim_title, sim_auth)

            if best_sim >= 0.70:
                fuzzy_matches.append((best_sim, row))

        fuzzy_matches.sort(key=lambda x: x[0], reverse=True)

        for sim, row in fuzzy_matches:
            key = f"book_{row['id']}"
            if key not in seen_keys:
                seen_keys.add(key)
                suggestions.append(
                    AutocompleteItem(
                        type="book",
                        id=row["id"],
                        title=row["title"],
                        author=row["author"],
                        match=norm_prefix,
                        isbn=row["isbn"],
                        category=row["category"],
                        publisher=row["publisher"],
                    )
                )
                if len(suggestions) >= limit:
                    return

    def clear_cache(self) -> None:
        """Clear the autocomplete LRU cache."""
        self._cache.clear()
