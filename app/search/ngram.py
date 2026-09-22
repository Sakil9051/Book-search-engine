"""
Character n-gram extraction and similarity computation.
Computes Dice and Jaccard coefficients over character grams for typo detection.
"""

from typing import List, Set
from app.search.normalizer import TextNormalizer


class NgramMatcher:
    """
    Computes character-level n-gram sets and similarity metrics.
    Robust against internal character transpositions and missing/extra letters.
    """

    @classmethod
    def get_ngrams(cls, text: str, n: int = 3) -> List[str]:
        """
        Extract overlapping character n-grams from normalized text.
        Adds boundary markers '^' and '$' for edge awareness.
        Example: 'atomic' with n=3 -> ['^at', 'ato', 'tom', 'omi', 'mic', 'ic$']
        """
        norm = TextNormalizer.normalize(text)
        if not norm:
            return []

        # If text is shorter than n, pad it with boundary symbols
        padded = f"^{norm}$"
        if len(padded) < n:
            return [padded]

        return [padded[i : i + n] for i in range(len(padded) - n + 1)]

    @classmethod
    def jaccard_similarity(cls, text1: str, text2: str, n: int = 3) -> float:
        """
        Compute Jaccard similarity: |A ∩ B| / |A ∪ B|
        """
        set1: Set[str] = set(cls.get_ngrams(text1, n))
        set2: Set[str] = set(cls.get_ngrams(text2, n))

        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0

        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        return intersection / union if union > 0 else 0.0

    @classmethod
    def dice_similarity(cls, text1: str, text2: str, n: int = 3) -> float:
        """
        Compute Dice coefficient: 2 * |A ∩ B| / (|A| + |B|)
        Dice gives more weight to matches, making it suitable for typo detection.
        """
        set1: Set[str] = set(cls.get_ngrams(text1, n))
        set2: Set[str] = set(cls.get_ngrams(text2, n))

        if not set1 and not set2:
            return 1.0
        if not set1 or not set2:
            return 0.0

        intersection = len(set1.intersection(set2))
        total = len(set1) + len(set2)
        return (2.0 * intersection) / total if total > 0 else 0.0

    @classmethod
    def similarity(cls, text1: str, text2: str) -> float:
        """
        Composite n-gram similarity:
        Blends bigram (n=2) and trigram (n=3) similarities.
        Bigrams help with short words; trigrams capture syllable order.
        """
        if not text1 or not text2:
            return 0.0
        if text1 == text2:
            return 1.0

        # For very short words (<= 3 chars), use bigrams primarily
        if len(text1) <= 3 or len(text2) <= 3:
            return cls.dice_similarity(text1, text2, n=2)

        bi_sim = cls.dice_similarity(text1, text2, n=2)
        tri_sim = cls.dice_similarity(text1, text2, n=3)

        # 40% bigram + 60% trigram
        return 0.4 * bi_sim + 0.6 * tri_sim
