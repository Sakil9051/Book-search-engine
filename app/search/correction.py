"""
Deterministic word-level and query-level spelling correction engine.
Combines dictionary frequencies, Levenshtein, Jaro-Winkler, n-grams,
phonetic keys, and book entity verification without any AI or external services.
"""

import math
import sqlite3
from typing import Dict, List, Optional, Tuple
from app.config import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM
from app.search.dictionary import DictionaryManager
from app.search.fuzzy import FuzzyMatcher
from app.search.normalizer import TextNormalizer
from app.search.phonetic import PhoneticMatcher
from app.search.tokenizer import Tokenizer


class SpellCorrector:
    """
    Spelling correction engine for bookstore queries.
    Identifies typographical errors, phonetic misspellings, and transposition mistakes.
    """

    def __init__(self, dict_manager: DictionaryManager, db_conn: Optional[sqlite3.Connection] = None):
        self.dict_manager = dict_manager
        self.db_conn = db_conn

    def correct_word(self, word: str) -> Tuple[str, float]:
        """
        Attempt to correct a single token against the dictionary.
        Returns (corrected_word, confidence_score_0_to_100).
        """
        w = TextNormalizer.normalize(word)
        if not w:
            return word, 0.0

        # Numbers, single letters, and known ISBN patterns don't need correction
        if w.isdigit() or len(w) <= 1:
            return w, 100.0

        # If word is already in the dictionary with good frequency
        freq = self.dict_manager.get_frequency(w)
        if freq >= 2:
            return w, 100.0

        candidates = self.dict_manager.get_candidates(w, max_edit_distance=2)
        if not candidates:
            # If no candidates found with distance 2, keep original
            return w, 50.0 if freq > 0 else 0.0

        best_word = w
        best_score = 0.0

        for cand_word, cand_freq in candidates:
            # Base word similarity (0.0 to 1.0)
            sim = FuzzyMatcher.word_similarity(w, cand_word)

            # Phonetic bonus (e.g. 'cleer' vs 'clear', 'poter' vs 'potter')
            phon_sim = PhoneticMatcher.word_phonetic_similarity(w, cand_word)
            if phon_sim >= 0.85:
                sim = max(sim, 0.85 + (0.15 * phon_sim))
            elif phon_sim >= 0.70:
                sim += 0.05

            # Frequency boost (logarithmic scale)
            freq_factor = min(0.10, math.log10(cand_freq + 1) * 0.03)
            total_cand_score = sim + freq_factor

            if total_cand_score > best_score:
                best_score = total_cand_score
                best_word = cand_word

        # If best match is strong enough (sim >= 0.72)
        if best_score >= 0.72 and best_word != w:
            confidence = min(99.0, best_score * 100.0)
            return best_word, confidence

        return w, 100.0 if freq > 0 else 50.0

    def correct_query(
        self, query: str, conn: Optional[sqlite3.Connection] = None
    ) -> Tuple[str, float, str, Optional[str]]:
        """
        Analyze and correct a full search query.
        Returns:
            (corrected_query, confidence_percentage, confidence_level, did_you_mean_title)
        """
        norm_query = TextNormalizer.normalize(query)
        if not norm_query:
            return "", 0.0, "LOW", None

        target_conn = conn or self.db_conn
        self.dict_manager.ensure_loaded(target_conn)

        # 1. First check search history learning & exact book aliases
        if target_conn:
            cursor = target_conn.cursor()

            # Check if an alias matches this query directly
            cursor.execute(
                """
                SELECT b.title, a.confidence
                FROM book_aliases a
                JOIN books b ON b.id = a.book_id
                WHERE a.normalized_alias = ?
                ORDER BY a.confidence DESC LIMIT 1
                """,
                (norm_query,),
            )
            alias_row = cursor.fetchone()
            if alias_row:
                title, conf = alias_row
                norm_title = TextNormalizer.normalize(title)
                confidence = float(conf) * 100.0 if conf <= 1.0 else float(conf)
                level = "HIGH" if confidence >= CONFIDENCE_HIGH else ("MEDIUM" if confidence >= CONFIDENCE_MEDIUM else "LOW")
                return norm_title, confidence, level, title

            # Check search logs for frequent user clicks on this query
            cursor.execute(
                """
                SELECT b.title, COUNT(*) as click_cnt
                FROM search_logs l
                JOIN books b ON b.id = l.clicked_book_id
                WHERE l.normalized_query = ? AND l.clicked_book_id IS NOT NULL
                GROUP BY b.id
                ORDER BY click_cnt DESC LIMIT 1
                """,
                (norm_query,),
            )
            click_row = cursor.fetchone()
            if click_row and click_row[1] >= 2:
                title, cnt = click_row
                norm_title = TextNormalizer.normalize(title)
                confidence = min(98.0, 85.0 + (cnt * 3.0))
                level = "HIGH" if confidence >= CONFIDENCE_HIGH else "MEDIUM"
                return norm_title, confidence, level, title

        # 2. Token-level dictionary spelling correction
        tokens = Tokenizer.tokenize(norm_query)
        if not tokens:
            return norm_query, 0.0, "LOW", None

        corrected_tokens = []
        token_confidences = []
        any_word_changed = False

        for token in tokens:
            corr_word, conf = self.correct_word(token)
            if corr_word != token:
                any_word_changed = True
            corrected_tokens.append(corr_word)
            token_confidences.append(conf)

        corrected_query = " ".join(corrected_tokens)

        # If no words changed, query is spelled correctly
        if not any_word_changed:
            return norm_query, 100.0, "HIGH", None

        # Calculate average token confidence
        avg_confidence = sum(token_confidences) / len(token_confidences)

        # 3. Check if the corrected query matches an existing book title or author in DB
        did_you_mean_title: Optional[str] = None
        if target_conn:
            cursor = target_conn.cursor()
            # Check exact or partial title match for corrected query
            cursor.execute(
                """
                SELECT title FROM books
                WHERE normalized_title = ? OR normalized_title LIKE ?
                ORDER BY popularity_score DESC LIMIT 1
                """,
                (corrected_query, f"%{corrected_query}%"),
            )
            title_row = cursor.fetchone()
            if title_row:
                did_you_mean_title = title_row[0]
                # Boost confidence because the corrected query directly forms a known book title!
                avg_confidence = max(avg_confidence, 94.0)

            if not did_you_mean_title:
                # Check author match
                cursor.execute(
                    """
                    SELECT author FROM books
                    WHERE normalized_author = ? OR normalized_author LIKE ?
                    LIMIT 1
                    """,
                    (corrected_query, f"%{corrected_query}%"),
                )
                auth_row = cursor.fetchone()
                if auth_row:
                    did_you_mean_title = auth_row[0]
                    avg_confidence = max(avg_confidence, 92.0)

        # Determine confidence level
        if avg_confidence >= CONFIDENCE_HIGH:
            level = "HIGH"
        elif avg_confidence >= CONFIDENCE_MEDIUM:
            level = "MEDIUM"
        else:
            level = "LOW"

        return corrected_query, round(avg_confidence, 1), level, did_you_mean_title
