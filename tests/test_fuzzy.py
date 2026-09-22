"""
Tests for FuzzyMatcher: Levenshtein, Jaro-Winkler, Token Sort/Set Ratio.
"""

from app.search.fuzzy import FuzzyMatcher


def test_levenshtein_distance():
    assert FuzzyMatcher.levenshtein_distance("potter", "poter") == 1
    assert FuzzyMatcher.levenshtein_distance("habits", "habbits") == 1
    assert FuzzyMatcher.levenshtein_distance("alchemist", "alchmist") == 1
    assert FuzzyMatcher.levenshtein_distance("clear", "clear") == 0


def test_damerau_transposition():
    # Adjacent character transposition distance is 1
    assert FuzzyMatcher.damerau_levenshtein_distance("teh", "the") == 1


def test_jaro_winkler_similarity():
    # Common prefix gets high similarity
    sim = FuzzyMatcher.jaro_winkler_similarity("potter", "poter")
    assert sim > 0.90

    sim_diff = FuzzyMatcher.jaro_winkler_similarity("potter", "alchemist")
    assert sim_diff < 0.50


def test_token_sort_ratio():
    # Handles word-order inversion
    ratio = FuzzyMatcher.token_sort_ratio("atomic habits", "habits atomic")
    assert ratio == 1.0


def test_token_set_ratio():
    # Handles subset and extra words
    ratio = FuzzyMatcher.token_set_ratio("psychology of money", "psychology money")
    assert ratio >= 0.90
