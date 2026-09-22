"""
Typo dictionary manager and dynamic typo learning system.
Loads and caches the common_typos table for sub-millisecond typo replacements.
Learns new typos deterministically from repeated user search clicks.
"""

import logging
import sqlite3
from typing import Dict, List, Optional, Tuple
from app.search.normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class TypoDictionary:
    """
    Manages deterministic typo-to-correction mappings in SQLite and memory.
    """

    def __init__(self, db_conn: Optional[sqlite3.Connection] = None):
        self.db_conn = db_conn
        # Cache: normalized_wrong_word -> (correct_word, confidence, frequency)
        self._cache: Dict[str, Tuple[str, float, int]] = {}
        self._is_loaded = False

    def load_typos(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """Load all entries from common_typos table into in-memory cache."""
        target_conn = conn or self.db_conn
        if target_conn is None:
            return

        try:
            cursor = target_conn.cursor()
            cursor.execute(
                """
                SELECT wrong_word, correct_word, confidence, frequency
                FROM common_typos
                """
            )
            rows = cursor.fetchall()

            self._cache.clear()
            for wrong, correct, conf, freq in rows:
                norm_wrong = TextNormalizer.normalize(wrong)
                norm_correct = TextNormalizer.normalize(correct)
                if norm_wrong and norm_correct:
                    self._cache[norm_wrong] = (norm_correct, float(conf), int(freq))

            self._is_loaded = True
            logger.info("Loaded %d common typos into in-memory cache", len(self._cache))
        except sqlite3.OperationalError as e:
            logger.warning("Could not load common_typos table: %s", e)

    def ensure_loaded(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """Ensure that the typo dictionary is loaded into memory."""
        if not self._is_loaded or not self._cache:
            self.load_typos(conn)

    def get_correction(
        self, wrong_word: str, conn: Optional[sqlite3.Connection] = None
    ) -> Optional[Tuple[str, float]]:
        """
        Check if wrong_word has a known correction in common typos.
        Returns: (correct_word, confidence) or None.
        """
        self.ensure_loaded(conn)
        norm_w = TextNormalizer.normalize(wrong_word)
        if norm_w in self._cache:
            correct, conf, _ = self._cache[norm_w]
            return correct, conf
        return None

    def lookup(
        self, wrong_word: str, conn: Optional[sqlite3.Connection] = None
    ) -> Optional[str]:
        """Convenience method returning just the corrected word string or None."""
        result = self.get_correction(wrong_word, conn)
        return result[0] if result else None

    def add_typo(
        self,
        wrong_word: str,
        correct_word: str,
        conn: Optional[sqlite3.Connection] = None,
        confidence: float = 95.0,
    ) -> bool:
        """Alias for learn_typo."""
        return self.learn_typo(wrong_word, correct_word, confidence, conn)

    def learn_typo(
        self,
        wrong_word: str,
        correct_word: str,
        confidence: float = 95.0,
        conn: Optional[sqlite3.Connection] = None,
    ) -> bool:
        """
        Learn or reinforce a typo mapping based on user search/click history.
        Increases frequency and reinforces confidence score.
        """
        norm_wrong = TextNormalizer.normalize(wrong_word)
        norm_correct = TextNormalizer.normalize(correct_word)

        if not norm_wrong or not norm_correct or norm_wrong == norm_correct:
            return False

        target_conn = conn or self.db_conn
        if target_conn:
            try:
                cursor = target_conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO common_typos (wrong_word, correct_word, frequency, confidence)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(wrong_word) DO UPDATE SET
                        frequency = frequency + 1,
                        confidence = MIN(99.0, MAX(common_typos.confidence, excluded.confidence) + 0.5),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (norm_wrong, norm_correct, confidence),
                )
                target_conn.commit()
            except Exception as e:
                logger.warning("Failed to persist learned typo %s -> %s: %s", norm_wrong, norm_correct, e)

        # Update in-memory cache
        curr = self._cache.get(norm_wrong)
        if curr:
            _, old_conf, old_freq = curr
            new_conf = min(99.0, max(old_conf, confidence) + 0.5)
            self._cache[norm_wrong] = (norm_correct, new_conf, old_freq + 1)
        else:
            self._cache[norm_wrong] = (norm_correct, confidence, 1)

        return True

    def get_all_typos(self) -> Dict[str, Tuple[str, float, int]]:
        """Return all cached typos."""
        self.ensure_loaded()
        return dict(self._cache)
