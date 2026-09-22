"""
Search history logging, telemetry, and deterministic click-based learning manager.
Tracks search_logs and discovers repeated typos and book associations without AI.
"""

import logging
import sqlite3
from typing import Dict, List, Optional, Tuple, Any
from app.search.normalizer import TextNormalizer
from app.search.tokenizer import Tokenizer
from app.search.typo import TypoDictionary

logger = logging.getLogger(__name__)


class SearchHistoryManager:
    """
    Manages search telemetry in search_logs and extracts learned typo patterns.
    """

    def __init__(
        self,
        db_conn: Optional[sqlite3.Connection] = None,
        typo_dict: Optional[TypoDictionary] = None,
    ):
        self.db_conn = db_conn
        self.typo_dict = typo_dict or TypoDictionary(db_conn)

    def log_search(
        self,
        query: str,
        normalized_query: str,
        corrected_query: Optional[str] = None,
        result_count: int = 0,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """
        Record a search event into search_logs.
        Returns the new log row ID.
        """
        target_conn = conn or self.db_conn
        if not target_conn or not query:
            return 0

        try:
            cursor = target_conn.cursor()
            cursor.execute(
                """
                INSERT INTO search_logs (query, normalized_query, corrected_query, result_count)
                VALUES (?, ?, ?, ?)
                """,
                (query, normalized_query, corrected_query, result_count),
            )
            target_conn.commit()
            return cursor.lastrowid or 0
        except Exception as e:
            logger.warning("Failed to log search event for '%s': %s", query, e)
            return 0

    def log_click(
        self,
        query: str,
        book_id: int,
        conn: Optional[sqlite3.Connection] = None,
    ) -> bool:
        """
        Record a user clicking a search result for a query.
        Learns from repeated clicks:
        - If query differs from the clicked book's title, learn word-level typos into common_typos.
        - Boost or add alias in book_aliases if click pattern is consistent.
        """
        target_conn = conn or self.db_conn
        if not target_conn or not query:
            return False

        norm_query = TextNormalizer.normalize(query)
        try:
            cursor = target_conn.cursor()

            # 1. Update the most recent matching log entry or insert a new one
            cursor.execute(
                """
                SELECT id FROM search_logs
                WHERE normalized_query = ? AND clicked_book_id IS NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (norm_query,),
            )
            recent_log = cursor.fetchone()

            if recent_log:
                cursor.execute(
                    "UPDATE search_logs SET clicked_book_id = ? WHERE id = ?",
                    (book_id, recent_log[0]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO search_logs (query, normalized_query, clicked_book_id, result_count)
                    VALUES (?, ?, ?, 1)
                    """,
                    (query, norm_query, book_id),
                )

            # 2. Retrieve clicked book title and author to extract word-level typo learning
            cursor.execute(
                "SELECT title, author, normalized_title, normalized_author FROM books WHERE id = ?",
                (book_id,),
            )
            book_row = cursor.fetchone()

            if book_row:
                norm_title = book_row["normalized_title"]
                norm_author = book_row["normalized_author"] or ""

                # If query doesn't match title exactly, inspect tokens
                if norm_query != norm_title and norm_query != norm_author:
                    self._extract_and_learn_typos(norm_query, norm_title, norm_author, target_conn)

                # Check total clicks for this query -> book_id
                cursor.execute(
                    """
                    SELECT COUNT(*) as clicks FROM search_logs
                    WHERE normalized_query = ? AND clicked_book_id = ?
                    """,
                    (norm_query, book_id),
                )
                clicks_cnt = cursor.fetchone()[0]

                # If 2 or more users clicked this book for this query, register as a book alias
                if clicks_cnt >= 2:
                    cursor.execute(
                        """
                        INSERT INTO book_aliases (book_id, alias, normalized_alias, source, confidence)
                        VALUES (?, ?, ?, 'search_history', 0.96)
                        ON CONFLICT DO NOTHING
                        """,
                        (book_id, query, norm_query),
                    )

            target_conn.commit()
            return True
        except Exception as e:
            logger.warning("Failed to log click for query '%s' and book %d: %s", query, book_id, e)
            return False

    def _extract_and_learn_typos(
        self,
        norm_query: str,
        norm_title: str,
        norm_author: str,
        conn: sqlite3.Connection,
    ) -> None:
        """
        Compare query tokens with book title/author tokens to learn misspelled words.
        """
        from app.search.fuzzy import FuzzyMatcher

        q_tokens = Tokenizer.tokenize(norm_query)
        target_tokens = Tokenizer.tokenize(f"{norm_title} {norm_author}")

        for qt in q_tokens:
            if qt.isdigit() or len(qt) <= 2:
                continue
            if qt in target_tokens:
                continue

            # Look for a close target token (similarity >= 0.75)
            for tt in target_tokens:
                if len(tt) <= 2 or tt.isdigit():
                    continue
                sim = FuzzyMatcher.word_similarity(qt, tt)
                if 0.70 <= sim < 1.0:
                    self.typo_dict.learn_typo(qt, tt, confidence=95.0, conn=conn)
                    break

    def get_history_learned_correction(
        self,
        normalized_query: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[Tuple[str, float, str]]:
        """
        Check if search history has strong click evidence for this query.
        Returns (norm_title, confidence, original_title) or None.
        """
        target_conn = conn or self.db_conn
        if not target_conn or not normalized_query:
            return None

        try:
            cursor = target_conn.cursor()
            cursor.execute(
                """
                SELECT b.title, b.normalized_title, COUNT(*) as click_cnt
                FROM search_logs l
                JOIN books b ON b.id = l.clicked_book_id
                WHERE l.normalized_query = ? AND l.clicked_book_id IS NOT NULL
                GROUP BY b.id
                ORDER BY click_cnt DESC LIMIT 1
                """,
                (normalized_query,),
            )
            row = cursor.fetchone()
            if row and row[2] >= 2:
                orig_title, norm_title, clicks = row
                confidence = min(98.5, 88.0 + (clicks * 2.5))
                return norm_title, confidence, orig_title
        except Exception as e:
            logger.warning("Error querying history corrections: %s", e)

        return None

    def get_search_statistics(self, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        """Retrieve aggregated search telemetry and learned pattern stats."""
        target_conn = conn or self.db_conn
        if not target_conn:
            return {"total_searches": 0, "total_clicks": 0, "top_queries": []}

        try:
            cursor = target_conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM search_logs")
            total_searches = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM search_logs WHERE clicked_book_id IS NOT NULL")
            total_clicks = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT query, COUNT(*) as cnt
                FROM search_logs
                GROUP BY normalized_query
                ORDER BY cnt DESC LIMIT 10
                """
            )
            top_queries = [{"query": r[0], "count": r[1]} for r in cursor.fetchall()]

            cursor.execute("SELECT COUNT(*) FROM common_typos")
            common_typos_count = cursor.fetchone()[0]

            return {
                "total_searches": total_searches,
                "total_clicks": total_clicks,
                "top_queries": top_queries,
                "learned_typos_count": common_typos_count,
            }
        except Exception as e:
            logger.warning("Error getting search statistics: %s", e)
            return {"total_searches": 0, "total_clicks": 0, "top_queries": []}
