"""
Book-specific search dictionary management and in-memory vocabulary caching.
Maintains token frequencies from books, authors, categories, publishers, aliases, and search logs.
"""

import sqlite3
import logging
from typing import Dict, List, Optional, Set, Tuple
from app.search.normalizer import TextNormalizer
from app.search.tokenizer import Tokenizer

logger = logging.getLogger(__name__)


class DictionaryManager:
    """
    Manages the search dictionary vocabulary in SQLite and memory.
    Provides fast candidate word retrieval for spell correction.
    """

    def __init__(self, db_conn: Optional[sqlite3.Connection] = None):
        self.db_conn = db_conn
        # In-memory dictionary cache: normalized_word -> frequency
        self._vocab: Dict[str, int] = {}
        # Inverted index by first letter for rapid pruning
        self._by_first_char: Dict[str, Set[str]] = {}
        # Pre-calculated word lengths
        self._by_length: Dict[int, Set[str]] = {}
        self._is_loaded = False

    def load_dictionary(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """
        Load search_dictionary into memory for zero-latency fuzzy lookups.
        """
        target_conn = conn or self.db_conn
        if target_conn is None:
            return

        cursor = target_conn.cursor()
        cursor.execute("SELECT normalized_word, frequency FROM search_dictionary")
        rows = cursor.fetchall()

        self._vocab.clear()
        self._by_first_char.clear()
        self._by_length.clear()

        for word, freq in rows:
            if not word:
                continue
            self._vocab[word] = freq
            first_char = word[0]
            self._by_first_char.setdefault(first_char, set()).add(word)
            self._by_length.setdefault(len(word), set()).add(word)

        self._is_loaded = True
        logger.info("Loaded %d words into in-memory search dictionary", len(self._vocab))

    def ensure_loaded(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """Ensure the vocabulary cache is loaded."""
        if not self._is_loaded or not self._vocab:
            self.load_dictionary(conn)

    def contains(self, word: str) -> bool:
        """Check if a word exists in the dictionary."""
        norm = TextNormalizer.normalize(word)
        return norm in self._vocab

    def get_frequency(self, word: str) -> int:
        """Get the occurrence frequency of a word."""
        norm = TextNormalizer.normalize(word)
        return self._vocab.get(norm, 0)

    def get_candidates(self, word: str, max_edit_distance: int = 2) -> List[Tuple[str, int]]:
        """
        Retrieve a pruned candidate set of dictionary words for a given target word:
        - Words with length within len(word) +/- max_edit_distance
        - High priority to words sharing the first letter, but also checks adjacent first letters.
        Returns list of (word, frequency).
        """
        w = TextNormalizer.normalize(word)
        if not w:
            return []

        w_len = len(w)
        candidate_words: Set[str] = set()

        # Length window
        min_len = max(1, w_len - max_edit_distance)
        max_len = w_len + max_edit_distance

        for l in range(min_len, max_len + 1):
            if l in self._by_length:
                candidate_words.update(self._by_length[l])

        # If vocabulary is large, filter by common characters
        char_set = set(w)
        filtered = []
        for cand in candidate_words:
            # Candidate must share at least 50% of characters
            shared = len(char_set.intersection(set(cand)))
            if shared >= max(1, len(char_set) // 2):
                filtered.append((cand, self._vocab[cand]))

        # Sort by frequency descending
        filtered.sort(key=lambda x: x[1], reverse=True)
        return filtered

    def rebuild_from_database(self, conn: sqlite3.Connection) -> int:
        """
        Scan all books, authors, categories, publishers, and aliases,
        tokenize them, and populate the search_dictionary table.
        """
        cursor = conn.cursor()
        freq_map: Dict[str, int] = {}
        source_map: Dict[str, str] = {}

        # 1. Words from Books
        cursor.execute("SELECT title, author, category, publisher FROM books")
        for title, author, category, publisher in cursor.fetchall():
            for text, src in [
                (title, "title"),
                (author, "author"),
                (category, "category"),
                (publisher, "publisher")
            ]:
                if not text:
                    continue
                tokens = Tokenizer.tokenize(text)
                for t in tokens:
                    if len(t) < 2 and not t.isdigit():
                        continue
                    freq_map[t] = freq_map.get(t, 0) + (3 if src == "title" else 2)
                    source_map[t] = src

        # 2. Words from Book Aliases
        cursor.execute("SELECT alias FROM book_aliases")
        for (alias,) in cursor.fetchall():
            if not alias:
                continue
            for t in Tokenizer.tokenize(alias):
                if len(t) < 2 and not t.isdigit():
                    continue
                freq_map[t] = freq_map.get(t, 0) + 2
                source_map[t] = "alias"

        # 3. Words from Search Logs
        cursor.execute("SELECT query, result_count FROM search_logs WHERE result_count > 0")
        for query, count in cursor.fetchall():
            if not query:
                continue
            for t in Tokenizer.tokenize(query):
                if len(t) < 2 and not t.isdigit():
                    continue
                freq_map[t] = freq_map.get(t, 0) + 1
                source_map[t] = "search_logs"

        # Upsert into search_dictionary
        for word, freq in freq_map.items():
            norm_word = TextNormalizer.normalize(word)
            src = source_map.get(word, "system")
            cursor.execute(
                """
                INSERT INTO search_dictionary (word, normalized_word, frequency, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    frequency = frequency + excluded.frequency,
                    source = excluded.source
                """,
                (word, norm_word, freq, src),
            )

        conn.commit()
        self.load_dictionary(conn)
        return len(freq_map)
