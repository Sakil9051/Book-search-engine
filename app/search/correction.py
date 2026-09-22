"""
Deterministic word-level and query-level spelling correction engine.
Combines dictionary frequencies, Levenshtein, Jaro-Winkler, n-grams,
phonetic keys, and book entity verification without any AI or external services.
"""

from app.search.spelling import SpellingCorrector

# Backward-compatible alias
SpellCorrector = SpellingCorrector
