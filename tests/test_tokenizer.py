"""
Tests for Tokenizer and Stemming.
"""

from app.search.tokenizer import Tokenizer


def test_tokenize():
    tokens = Tokenizer.tokenize("The Psychology of Money")
    assert tokens == ["the", "psychology", "of", "money"]


def test_filter_stop_words():
    tokens = ["the", "psychology", "of", "money"]
    filtered = Tokenizer.filter_stop_words(tokens)
    assert filtered == ["psychology", "money"]


def test_stemming():
    assert Tokenizer.stem("habits") == "habit"
    assert Tokenizer.stem("books") == "book"
    assert Tokenizer.stem("potter") == "potter"


def test_stem_tokens():
    stems = Tokenizer.stem_tokens(["atomic", "habits", "books"])
    assert stems == ["atomic", "habit", "book"]
