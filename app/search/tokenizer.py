"""
Query tokenization, stop-word classification, and lightweight stemming.
Preserves original query structure while providing filtered/stemmed views for ranking.
"""

from typing import List, Set
from app.search.normalizer import TextNormalizer


class Tokenizer:
    """
    Splits text into tokens, classifies stop words, and applies lightweight
    stemming without external dependencies or aggressive over-stemming.
    """

    STOP_WORDS: Set[str] = {
        "the", "a", "an", "of", "and", "in", "on", "for", "to", "is", "are",
        "book", "by", "with", "at", "from", "be", "this", "that", "it", "as",
        "or", "about", "into", "through", "during", "before", "after"
    }

    # Irregular plural mapping
    IRREGULAR_STEMS = {
        "stories": "story",
        "memories": "memory",
        "mysteries": "mystery",
        "histories": "history",
        "centuries": "century",
        "companies": "company",
        "people": "person",
        "children": "child",
        "women": "woman",
        "men": "man",
        "lives": "life",
        "knives": "knife",
        "leaves": "leaf",
        "halves": "half",
    }

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        """
        Tokenize a string into words after normalization.
        Returns all tokens including stop words.
        """
        norm = TextNormalizer.normalize(text)
        if not norm:
            return []
        return norm.split()

    @classmethod
    def is_stop_word(cls, word: str) -> bool:
        """Check if a token is a recognized stop word."""
        return word.lower() in cls.STOP_WORDS

    @classmethod
    def filter_stop_words(cls, tokens: List[str]) -> List[str]:
        """
        Filter out stop words from a token list.
        Useful for ranking and keyword-specific similarity.
        """
        return [t for t in tokens if t not in cls.STOP_WORDS]

    @classmethod
    def stem(cls, word: str) -> str:
        """
        Lightweight conservative stemming algorithm:
        Handles plurals and common inflections without over-stemming proper names or titles.
        """
        w = word.lower()
        if len(w) <= 3:
            return w

        # Check irregular stem table
        if w in cls.IRREGULAR_STEMS:
            return cls.IRREGULAR_STEMS[w]

        # Suffix: -ies -> -y (e.g. 'stories' -> 'story', 'categories' -> 'category')
        if w.endswith("ies") and len(w) > 4:
            return w[:-3] + "y"

        # Suffix: -sses -> -ss (e.g. 'businesses' -> 'business', 'processes' -> 'process')
        if w.endswith("sses") and len(w) > 5:
            return w[:-2]

        # Suffix: -ches, -shes, -xes, -zes -> strip -es (e.g. 'searches' -> 'search')
        if len(w) > 4:
            for ending in ("ches", "shes", "xes", "zes"):
                if w.endswith(ending):
                    return w[:-2]

        # Suffix: general plural -s (e.g. 'habits' -> 'habit', 'books' -> 'book')
        # Do not strip if ends in double 'ss' (e.g., 'business', 'glass', 'grass')
        # or if length <= 3
        if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            return w[:-1]

        return w

    @classmethod
    def stem_tokens(cls, tokens: List[str]) -> List[str]:
        """Stem a list of tokens."""
        return [cls.stem(t) for t in tokens]

    @classmethod
    def are_stems_equal(cls, word1: str, word2: str) -> bool:
        """Determine if two words share the same stem."""
        return cls.stem(word1) == cls.stem(word2)
