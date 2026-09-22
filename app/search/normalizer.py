"""
Text normalization utility module for deterministic search processing.
Handles Unicode, casing, punctuation, hyphens, apostrophes, and token sorting.
"""

import re
import unicodedata
from typing import List, Optional


class TextNormalizer:
    """
    Reusable text normalization engine.
    Ensures deterministic, uniform string representations for indexing and matching.
    """

    # Regex patterns compiled once for performance
    _RE_SPACES = re.compile(r"\s+")
    _RE_HYPHENS = re.compile(r"[-_—–]+")
    # Apostrophes: single quote, typographic quotes, backticks
    _RE_APOSTROPHES = re.compile(r"['`’‘‛]")
    # Allowed in normalized text: lowercase a-z, numbers 0-9, and single spaces
    _RE_PUNCTUATION = re.compile(r"[^\w\s]")
    # Match ISBN (10 or 13 digits, optional hyphens/spaces, possible 'X' at end of ISBN-10)
    _RE_ISBN = re.compile(r"^(?:97[89][-\s]?)?(?:\d[-\s]?){9}[\dXx]$")

    @classmethod
    def strip_accents(cls, text: str) -> str:
        """
        Decompose Unicode characters and remove diacritical marks.
        Example: 'café' -> 'cafe', 'naïve' -> 'naive'
        """
        if not text:
            return ""
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(c for c in normalized if not unicodedata.combining(c))

    @classmethod
    def normalize(cls, text: Optional[str]) -> str:
        """
        Primary normalization routine:
        - None-safe
        - Unicode decomposition
        - Lowercase
        - Hyphens to spaces
        - Remove/standardize apostrophes
        - Remove remaining punctuation
        - Condense whitespace
        - Strip leading/trailing spaces
        """
        if text is None:
            return ""

        # Step 1: Strip Unicode accents/diacritics
        s = cls.strip_accents(text)

        # Step 2: Convert to lowercase
        s = s.lower()

        # Step 3: Replace hyphens and dashes with space
        # e.g., "Harry-Potter" -> "harry potter"
        s = cls._RE_HYPHENS.sub(" ", s)

        # Step 4: Remove apostrophes cleanly
        # e.g. "philosopher's" -> "philosophers", "don't" -> "dont"
        s = cls._RE_APOSTROPHES.sub("", s)

        # Step 5: Replace other punctuation and special characters with spaces
        # e.g. "HARRY, POTTER!" -> "harry  potter "
        s = cls._RE_PUNCTUATION.sub(" ", s)

        # Step 6: Convert multiple consecutive whitespace characters into a single space
        s = cls._RE_SPACES.sub(" ", s)

        # Step 7: Trim leading and trailing whitespace
        return s.strip()

    @classmethod
    def normalize_word_order(cls, text: Optional[str]) -> str:
        """
        Normalize word order for token-order-independent comparison.
        Sorts the individual normalized words alphabetically.
        Example: 'habits atomic' -> 'atomic habits'
        """
        norm = cls.normalize(text)
        if not norm:
            return ""
        tokens = sorted(norm.split())
        return " ".join(tokens)

    @classmethod
    def is_isbn(cls, text: Optional[str]) -> bool:
        """Check whether the input string matches valid ISBN-10 or ISBN-13 format."""
        if not text:
            return False
        clean = text.strip().replace("-", "").replace(" ", "").upper()
        if len(clean) not in (10, 13):
            return False
        if len(clean) == 10:
            return clean[:9].isdigit() and (clean[9].isdigit() or clean[9] == "X")
        return clean.isdigit()

    @classmethod
    def clean_isbn(cls, text: Optional[str]) -> Optional[str]:
        """Strip formatting from an ISBN, returning pure uppercase alphanumeric digits."""
        if not text:
            return None
        clean = text.strip().replace("-", "").replace(" ", "").upper()
        if cls.is_isbn(clean):
            return clean
        return None
