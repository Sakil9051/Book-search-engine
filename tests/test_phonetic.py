"""
Tests for PhoneticMatcher: Soundex and Metaphone.
"""

from app.search.phonetic import PhoneticMatcher


def test_soundex_homophones():
    # 'Clear' and 'Cleer' produce the same soundex code
    assert PhoneticMatcher.soundex("clear") == PhoneticMatcher.soundex("cleer")
    assert PhoneticMatcher.soundex("smith") == PhoneticMatcher.soundex("smyth")


def test_metaphone_keys():
    # 'Clear' and 'Cleer' produce the exact same acoustic key
    assert PhoneticMatcher.metaphone("clear") == PhoneticMatcher.metaphone("cleer")
    # 'Psychology' has silent P
    assert PhoneticMatcher.metaphone("psychology") == "SKLJ"


def test_phonetic_similarity():
    sim = PhoneticMatcher.word_phonetic_similarity("cleer", "clear")
    assert sim >= 0.90

    sim_diff = PhoneticMatcher.word_phonetic_similarity("atomic", "harry")
    assert sim_diff == 0.0
