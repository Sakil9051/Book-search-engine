"""
Deterministic word-level and query-level automatic spelling corrector.
Implements the 10-step correction algorithm, confidence scoring (0-100),
multi-word correction, author correction, and book entity verification.
"""

import math
import re
import sqlite3
import logging
from typing import Dict, List, Optional, Tuple, Set
from app.config import CONFIDENCE_HIGH, CONFIDENCE_MEDIUM
from app.search.dictionary import DictionaryManager
from app.search.fuzzy import FuzzyMatcher
from app.search.ngram import NgramMatcher
from app.search.normalizer import TextNormalizer
from app.search.phonetic import PhoneticMatcher
from app.search.tokenizer import Tokenizer
from app.search.typo import TypoDictionary

logger = logging.getLogger(__name__)


class SpellingCorrector:
    """
    Dedicated spelling correction engine for bookstore queries.
    Performs 10-step token-level candidate evaluation and whole-query verification.
    """

    def __init__(
        self,
        dict_manager: Optional[DictionaryManager] = None,
        db_conn: Optional[sqlite3.Connection] = None,
        typo_dict: Optional[TypoDictionary] = None,
    ):
        self.dict_manager = dict_manager or DictionaryManager()
        self.db_conn = db_conn
        self.typo_dict = typo_dict or TypoDictionary(db_conn)

    def is_protected_token(self, token: str) -> bool:
        """
        Check if a token should NOT be modified:
        - ISBN numbers or pure digits
        - Extremely short tokens (single letters)
        - Alphanumeric codes / SKUs
        """
        if not token or len(token) <= 1:
            return True
        if token.isdigit():
            return True
        # Clean ISBN check (e.g. 10 or 13 digits, or ending with X)
        cleaned = re.sub(r"[\s\-]", "", token)
        if (len(cleaned) in (10, 13) and cleaned[:-1].isdigit()) or (len(cleaned) == 10 and cleaned[-1].upper() == "X"):
            return True
        return False

    def correct_word(
        self,
        word: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Tuple[str, float]:
        """
        10-Step Word Correction Algorithm:
        1. Check exact dictionary match.
        2. Check known aliases.
        3. Check common typo dictionary.
        4. Check prefix candidates.
        5. Calculate Levenshtein similarity.
        6. Calculate Jaro-Winkler similarity.
        7. Calculate n-gram similarity.
        8. Calculate phonetic similarity.
        9. Calculate word frequency.
        10. Select the best candidate.

        Returns (corrected_word, confidence_0_to_100).
        """
        w = TextNormalizer.normalize(word)
        if not w:
            return word, 0.0

        # Step 0: Protected token check (ISBN, SKU, digits, single chars)
        if self.is_protected_token(w):
            return w, 100.0

        target_conn = conn or self.db_conn
        self.dict_manager.ensure_loaded(target_conn)
        self.typo_dict.ensure_loaded(target_conn)

        # Step 1: Check common typo dictionary (seeded + learned from user search history)
        typo_match = self.typo_dict.get_correction(w, target_conn)
        if typo_match:
            correct_word, conf = typo_match
            return correct_word, conf

        # Step 2: Check exact dictionary match (valid vocabulary word)
        freq = self.dict_manager.get_frequency(w)
        if freq >= 2:
            # Word is well-known in the bookstore database (e.g., "potter" shouldn't become "poter")
            return w, 100.0

        # Step 2: Check known aliases table directly for single-word alias
        if target_conn:
            try:
                cursor = target_conn.cursor()
                cursor.execute(
                    """
                    SELECT b.normalized_title, a.confidence
                    FROM book_aliases a
                    JOIN books b ON b.id = a.book_id
                    WHERE a.normalized_alias = ?
                    LIMIT 1
                    """,
                    (w,),
                )
                alias_row = cursor.fetchone()
                if alias_row:
                    norm_title, conf = alias_row
                    # If alias points to a single word title or matches title exactly
                    tokens = norm_title.split()
                    if len(tokens) == 1:
                        return tokens[0], min(99.0, float(conf) * 100.0)
            except Exception:
                pass

        # Step 4: Retrieve candidate set from dictionary within edit distance <= 2
        candidates = self.dict_manager.get_candidates(w, max_edit_distance=2)
        if not candidates:
            # If word is in dictionary even with freq 1, keep it
            return w, (100.0 if freq > 0 else 50.0)

        best_word = w
        best_composite_score = 0.0
        best_sim = 0.0

        for cand_word, cand_freq in candidates:
            if cand_word == w:
                continue

            # Step 5: Levenshtein distance & similarity
            lev_dist = FuzzyMatcher.levenshtein_distance(w, cand_word)
            lev_sim = FuzzyMatcher.levenshtein_similarity(w, cand_word)

            # Step 6: Jaro-Winkler similarity
            jw_sim = FuzzyMatcher.jaro_winkler_similarity(w, cand_word)

            # Step 7: N-gram similarity (trigrams/bigrams)
            ng_sim = NgramMatcher.similarity(w, cand_word)

            # Step 8: Phonetic similarity (Double Metaphone / Soundex)
            phon_sim = PhoneticMatcher.word_phonetic_similarity(w, cand_word)

            # Base lexical similarity (weighted average)
            lex_sim = (0.45 * jw_sim) + (0.35 * lev_sim) + (0.20 * ng_sim)

            # Phonetic bonus (e.g. 'cleer' -> 'clear', 'poter' -> 'potter')
            if phon_sim >= 0.85:
                lex_sim = max(lex_sim, 0.85 + (0.15 * phon_sim))
            elif phon_sim >= 0.70:
                lex_sim += 0.05

            # Step 9: Word frequency weighting (logarithmic dampening)
            freq_bonus = min(0.08, math.log10(cand_freq + 1) * 0.025)

            # Composite candidate score
            composite = lex_sim + freq_bonus

            # Step 10: Select best candidate
            if composite > best_composite_score:
                best_composite_score = composite
                best_sim = lex_sim
                best_word = cand_word

        # Threshold check: do NOT correct if similarity is too low
        # If similarity < 0.70 (confidence < 70), do not correct
        if best_sim >= 0.72 and best_word != w:
            confidence = min(98.5, max(70.0, best_sim * 100.0))
            return best_word, round(confidence, 1)

        # Retain original word if confidence < 70
        return w, (100.0 if freq > 0 else 50.0)

    def correct_query(
        self,
        query: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Tuple[str, float, str, Optional[str]]:
        """
        Analyze and correct a full user search query.
        Handles:
        - Multi-word corrections (e.g., 'atomic habbits james cleer' -> 'atomic habits james clear')
        - Author corrections ('james cleer' -> 'James Clear', 'cohelo' -> 'Paulo Coelho')
        - Missing words ('psychology money' -> 'The Psychology of Money')
        - Word order independence
        - Learning from search history and aliases

        Returns:
            (corrected_query, confidence_score_0_to_100, confidence_level, did_you_mean_title)
        """
        norm_query = TextNormalizer.normalize(query)
        if not norm_query:
            return "", 0.0, "LOW", None

        target_conn = conn or self.db_conn
        self.dict_manager.ensure_loaded(target_conn)
        self.typo_dict.ensure_loaded(target_conn)

        # 1. Exact Book Aliases Check
        if target_conn:
            try:
                cursor = target_conn.cursor()
                cursor.execute(
                    """
                    SELECT b.title, b.normalized_title, a.confidence
                    FROM book_aliases a
                    JOIN books b ON b.id = a.book_id
                    WHERE a.normalized_alias = ?
                    ORDER BY a.confidence DESC LIMIT 1
                    """,
                    (norm_query,),
                )
                alias_row = cursor.fetchone()
                if alias_row:
                    title, norm_title, conf = alias_row
                    confidence = float(conf) * 100.0 if conf <= 1.0 else float(conf)
                    confidence = min(99.0, max(confidence, 94.0))
                    level = "HIGH" if confidence >= CONFIDENCE_HIGH else "MEDIUM"
                    return norm_title, confidence, level, title
            except Exception as e:
                logger.warning("Error checking book aliases: %s", e)

        # 2. Search History Telemetry Check (repeated clicks for this query)
        if target_conn:
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
                    (norm_query,),
                )
                click_row = cursor.fetchone()
                if click_row and click_row[2] >= 2:
                    title, norm_title, cnt = click_row
                    confidence = min(98.5, 88.0 + (cnt * 2.5))
                    level = "HIGH" if confidence >= CONFIDENCE_HIGH else "MEDIUM"
                    return norm_title, round(confidence, 1), level, title
            except Exception as e:
                logger.warning("Error checking search logs: %s", e)

        # 3. Token-by-Token Multi-Word Spelling Correction
        tokens = Tokenizer.tokenize(norm_query)
        if not tokens:
            return norm_query, 0.0, "LOW", None

        corrected_tokens = []
        token_confidences = []
        words_changed_count = 0

        for token in tokens:
            corr_word, conf = self.correct_word(token, target_conn)
            if corr_word != token:
                words_changed_count += 1
            corrected_tokens.append(corr_word)
            token_confidences.append(conf)

        corrected_query = " ".join(corrected_tokens)

        # If no words changed, verify if all tokens are recognized
        if words_changed_count == 0:
            avg_conf = sum(token_confidences) / len(token_confidences) if token_confidences else 100.0
            if any(conf < 70.0 for conf in token_confidences):
                return norm_query, round(avg_conf, 1), "LOW", None
            return norm_query, 100.0, "HIGH", None

        # Calculate average token confidence
        avg_confidence = sum(token_confidences) / len(token_confidences)

        # 4. Check if the corrected query maps to one or more real books or authors
        did_you_mean_title: Optional[str] = None
        book_match_found = False

        if target_conn:
            try:
                cursor = target_conn.cursor()
                # Check for exact or prefix title match
                cursor.execute(
                    """
                    SELECT title, normalized_title FROM books
                    WHERE normalized_title = ? OR normalized_title LIKE ?
                    ORDER BY popularity_score DESC LIMIT 1
                    """,
                    (corrected_query, f"%{corrected_query}%"),
                )
                title_row = cursor.fetchone()
                if title_row:
                    did_you_mean_title = title_row[0]
                    book_match_found = True
                    # Significant boost: corrected query forms an authentic book title in catalog!
                    avg_confidence = max(avg_confidence, 95.5)

                if not did_you_mean_title:
                    # Check author match (e.g. 'james cleer' -> 'james clear' matches author James Clear)
                    cursor.execute(
                        """
                        SELECT b.title, b.author FROM books b
                        WHERE normalized_author = ? OR normalized_author LIKE ?
                        ORDER BY popularity_score DESC LIMIT 1
                        """,
                        (corrected_query, f"%{corrected_query}%"),
                    )
                    auth_row = cursor.fetchone()
                    if auth_row:
                        did_you_mean_title = f"{auth_row[0]} by {auth_row[1]}"
                        book_match_found = True
                        avg_confidence = max(avg_confidence, 93.0)

                if not did_you_mean_title:
                    # Check FTS5 token intersection to verify real books exist
                    clean_fts = " ".join(t for t in corrected_tokens if len(t) > 2)
                    if clean_fts:
                        cursor.execute(
                            """
                            SELECT b.title FROM books_fts f
                            JOIN books b ON b.id = f.rowid
                            WHERE books_fts MATCH ?
                            LIMIT 1
                            """,
                            (clean_fts,),
                        )
                        fts_row = cursor.fetchone()
                        if fts_row:
                            did_you_mean_title = fts_row[0]
                            book_match_found = True
                            avg_confidence = max(avg_confidence, 91.0)
            except Exception as e:
                logger.warning("Error verifying book entity match: %s", e)

        # 5. Apply Confidence System Rules (Section 5 & 8)
        # 90-100: HIGH CONFIDENCE -> Automatically correct if mapped to real book
        # 70-89: MEDIUM CONFIDENCE -> Show "Did you mean..."
        # Below 70: Do not correct
        if avg_confidence >= CONFIDENCE_HIGH and book_match_found:
            level = "HIGH"
        elif avg_confidence >= CONFIDENCE_MEDIUM:
            level = "MEDIUM"
        else:
            level = "LOW"
            # Do not correct when confidence is low
            corrected_query = norm_query
            did_you_mean_title = None

        return corrected_query, round(avg_confidence, 1), level, did_you_mean_title
