"""
Tests for TextNormalizer.
"""

from app.search.normalizer import TextNormalizer


def test_lowercase():
    assert TextNormalizer.normalize("Atomic Habits") == "atomic habits"
    assert TextNormalizer.normalize("HARRY POTTER") == "harry potter"


def test_strip_punctuation():
    assert TextNormalizer.normalize("Harry Potter: The Chamber of Secrets!") == "harry potter the chamber of secrets"
    assert TextNormalizer.normalize("Can't Hurt Me!") == "cant hurt me"
    assert TextNormalizer.normalize("Thinking, Fast and Slow...") == "thinking fast and slow"


def test_unicode_accents():
    assert TextNormalizer.normalize("Paulo Coêlho") == "paulo coelho"
    assert TextNormalizer.normalize("Françesc Miralles") == "francesc miralles"


def test_collapse_whitespace():
    assert TextNormalizer.normalize("  Atomic    Habits  \n\t ") == "atomic habits"


def test_clean_isbn():
    assert TextNormalizer.clean_isbn("978-0-7352-1129-2") == "9780735211292"
    assert TextNormalizer.clean_isbn("0-7475-3274-5") == "0747532745"
    assert TextNormalizer.clean_isbn("invalid-isbn") is None
    assert TextNormalizer.clean_isbn("") is None


def test_word_order_normalization():
    assert TextNormalizer.normalize_word_order("habits atomic") == "atomic habits"
    assert TextNormalizer.normalize_word_order("rich grow think and") == "and grow rich think"
