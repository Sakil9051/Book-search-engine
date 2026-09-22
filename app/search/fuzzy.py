"""
Fuzzy string matching algorithms.
Implements Levenshtein distance, Damerau-Levenshtein, Jaro-Winkler,
Token Sort Ratio, Token Set Ratio, and Composite similarity scoring.
"""

from typing import List, Set
from app.search.normalizer import TextNormalizer
from app.search.ngram import NgramMatcher
from app.search.phonetic import PhoneticMatcher


class FuzzyMatcher:
    """
    Multi-algorithm deterministic fuzzy matching engine.
    Does not rely on a single metric; combines edit distance,
    prefix weighting, n-grams, and set coverage.
    """

    @classmethod
    def levenshtein_distance(cls, s1: str, s2: str) -> int:
        """
        Compute standard Levenshtein edit distance between two strings.
        Space-optimized O(min(N, M)) implementation.
        """
        if s1 == s2:
            return 0
        if not s1:
            return len(s2)
        if not s2:
            return len(s1)

        if len(s1) < len(s2):
            s1, s2 = s2, s1

        # s1 is longer or equal to s2
        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1] * (len(s2) + 1)
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row[j + 1] = min(insertions, deletions, substitutions)
            previous_row = current_row

        return previous_row[-1]

    @classmethod
    def damerau_levenshtein_distance(cls, s1: str, s2: str) -> int:
        """
        Damerau-Levenshtein distance (includes adjacent transpositions, e.g. 'alchmist' <-> 'alchemist').
        """
        if s1 == s2:
            return 0
        len1, len2 = len(s1), len(s2)
        if not len1:
            return len2
        if not len2:
            return len1

        # Matrix of size (len1 + 1) x (len2 + 1)
        d = [[0] * (len2 + 1) for _ in range(len1 + 1)]

        for i in range(len1 + 1):
            d[i][0] = i
        for j in range(len2 + 1):
            d[0][j] = j

        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                d[i][j] = min(
                    d[i - 1][j] + 1,        # deletion
                    d[i][j - 1] + 1,        # insertion
                    d[i - 1][j - 1] + cost  # substitution
                )
                # Check transposition
                if i > 1 and j > 1 and s1[i - 1] == s2[j - 2] and s1[i - 2] == s2[j - 1]:
                    d[i][j] = min(d[i][j], d[i - 2][j - 2] + cost)

        return d[len1][len2]

    @classmethod
    def levenshtein_similarity(cls, s1: str, s2: str) -> float:
        """
        Normalize Levenshtein distance to a similarity ratio between 0.0 and 1.0.
        """
        n1 = TextNormalizer.normalize(s1)
        n2 = TextNormalizer.normalize(s2)
        if n1 == n2:
            return 1.0
        max_len = max(len(n1), len(n2))
        if max_len == 0:
            return 1.0
        dist = cls.damerau_levenshtein_distance(n1, n2)
        return max(0.0, 1.0 - (dist / max_len))

    @classmethod
    def jaro_similarity(cls, s1: str, s2: str) -> float:
        """
        Compute Jaro distance between two strings.
        """
        if s1 == s2:
            return 1.0
        len1, len2 = len(s1), len(s2)
        if len1 == 0 or len2 == 0:
            return 0.0

        match_bound = max(len1, len2) // 2 - 1
        if match_bound < 0:
            match_bound = 0

        s1_matches = [False] * len1
        s2_matches = [False] * len2

        matches = 0
        for i in range(len1):
            start = max(0, i - match_bound)
            end = min(i + match_bound + 1, len2)
            for j in range(start, end):
                if not s2_matches[j] and s1[i] == s2[j]:
                    s1_matches[i] = True
                    s2_matches[j] = True
                    matches += 1
                    break

        if matches == 0:
            return 0.0

        # Count transpositions
        k = 0
        transpositions = 0
        for i in range(len1):
            if s1_matches[i]:
                while not s2_matches[k]:
                    k += 1
                if s1[i] != s2[k]:
                    transpositions += 1
                k += 1

        transpositions //= 2
        return (
            (matches / len1) +
            (matches / len2) +
            ((matches - transpositions) / matches)
        ) / 3.0

    @classmethod
    def jaro_winkler_similarity(cls, s1: str, s2: str, p: float = 0.1, max_l: int = 4) -> float:
        """
        Compute Jaro-Winkler similarity.
        Awards higher similarity to strings that share a common prefix.
        """
        n1 = TextNormalizer.normalize(s1)
        n2 = TextNormalizer.normalize(s2)
        if n1 == n2:
            return 1.0

        jaro_dist = cls.jaro_similarity(n1, n2)

        # Common prefix length up to max_l characters
        l = 0
        for i in range(min(len(n1), len(n2), max_l)):
            if n1[i] == n2[i]:
                l += 1
            else:
                break

        return jaro_dist + (l * p * (1.0 - jaro_dist))

    @classmethod
    def token_sort_ratio(cls, s1: str, s2: str) -> float:
        """
        Token sort similarity ratio:
        Splits strings into tokens, sorts tokens alphabetically, then compares.
        Example: 'habits atomic' and 'atomic habits' -> 1.0!
        """
        sorted_s1 = TextNormalizer.normalize_word_order(s1)
        sorted_s2 = TextNormalizer.normalize_word_order(s2)
        return cls.levenshtein_similarity(sorted_s1, sorted_s2)

    @classmethod
    def token_set_ratio(cls, s1: str, s2: str) -> float:
        """
        Token set similarity ratio:
        Extracts unique tokens from both strings, partitions into:
        - Common tokens
        - Remainder in s1
        - Remainder in s2
        Computes maximum similarity across permutations.
        Handles missing and extra words robustly (e.g. 'psychology money' vs 'the psychology of money').
        """
        tokens1: Set[str] = set(TextNormalizer.normalize(s1).split())
        tokens2: Set[str] = set(TextNormalizer.normalize(s2).split())

        if not tokens1 or not tokens2:
            return 0.0

        intersection = sorted(tokens1.intersection(tokens2))
        diff1 = sorted(tokens1 - tokens2)
        diff2 = sorted(tokens2 - tokens1)

        t_inter = " ".join(intersection)
        t_1 = " ".join(diff1)
        t_2 = " ".join(diff2)

        if not t_inter:
            # No common tokens, fallback to regular similarity
            return cls.token_sort_ratio(s1, s2)

        # Build candidate comparisons
        cand1 = t_inter
        cand2 = f"{t_inter} {t_1}".strip()
        cand3 = f"{t_inter} {t_2}".strip()

        scores = [
            cls.levenshtein_similarity(cand1, cand2),
            cls.levenshtein_similarity(cand1, cand3),
            cls.levenshtein_similarity(cand2, cand3),
            cls.token_sort_ratio(s1, s2),
        ]

        # If one string is a subset of the other, token set ratio is very high
        if tokens1.issubset(tokens2) or tokens2.issubset(tokens1):
            # Coverage percentage
            coverage = len(intersection) / min(len(tokens1), len(tokens2))
            scores.append(coverage)

        return max(scores)

    @classmethod
    def word_similarity(cls, word1: str, word2: str) -> float:
        """
        Calculate composite word-level similarity.
        Combines Levenshtein, Jaro-Winkler, and N-gram overlap.
        """
        w1 = TextNormalizer.normalize(word1)
        w2 = TextNormalizer.normalize(word2)

        if not w1 or not w2:
            return 0.0
        if w1 == w2:
            return 1.0

        lev = cls.levenshtein_similarity(w1, w2)
        jw = cls.jaro_winkler_similarity(w1, w2)
        ngram = NgramMatcher.similarity(w1, w2)

        # Weighted blend for individual words:
        # Jaro-Winkler 40%, Levenshtein 35%, N-gram 25%
        return 0.40 * jw + 0.35 * lev + 0.25 * ngram

    @classmethod
    def string_similarity(cls, s1: str, s2: str) -> float:
        """
        Full string similarity:
        Blends Token Set Ratio (40%), Token Sort Ratio (25%),
        Jaro-Winkler (20%), and N-gram (15%).
        """
        n1 = TextNormalizer.normalize(s1)
        n2 = TextNormalizer.normalize(s2)

        if not n1 or not n2:
            return 0.0
        if n1 == n2:
            return 1.0

        set_ratio = cls.token_set_ratio(n1, n2)
        sort_ratio = cls.token_sort_ratio(n1, n2)
        jw = cls.jaro_winkler_similarity(n1, n2)
        ngram = NgramMatcher.similarity(n1, n2)

        return (0.40 * set_ratio) + (0.25 * sort_ratio) + (0.20 * jw) + (0.15 * ngram)
