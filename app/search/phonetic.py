"""
Phonetic matching algorithms: Soundex and Metaphone.
Provides phonetic encoding and similarity scoring to detect phonetically identical
or similar sounding typos (especially effective for author names like 'cleer' -> 'clear').
"""

import re
from typing import List, Optional
from app.search.normalizer import TextNormalizer


class PhoneticMatcher:
    """
    Deterministic phonetic encoder and similarity evaluator.
    Pure Python, zero external AI/LLM or third-party binary dependencies.
    """

    # Soundex mapping table
    _SOUNDEX_MAP = {
        "b": "1", "f": "1", "p": "1", "v": "1",
        "c": "2", "g": "2", "j": "2", "k": "2", "q": "2", "s": "2", "x": "2", "z": "2",
        "d": "3", "t": "3",
        "l": "4",
        "m": "5", "n": "5",
        "r": "6",
    }

    @classmethod
    def soundex(cls, word: str) -> str:
        """
        Compute standard American Soundex code (e.g. 'Clear' -> 'C460', 'Cleer' -> 'C460').
        Returns 4-character code (First letter + 3 digits).
        """
        if not word:
            return ""
        word = TextNormalizer.normalize(word)
        if not word:
            return ""

        first_letter = word[0].upper()
        digits = []

        prev_code = cls._SOUNDEX_MAP.get(word[0], "0")

        for char in word[1:]:
            code = cls._SOUNDEX_MAP.get(char, "0")
            if code != "0":
                if code != prev_code:
                    digits.append(code)
                prev_code = code
            else:
                # Vowels and h/w reset previous code rule in standard Soundex
                if char in "aeiouy":
                    prev_code = "0"

        # Pad with zeros or truncate to 3 digits
        result = first_letter + "".join(digits)
        result = (result + "000")[:4]
        return result

    @classmethod
    def metaphone(cls, word: str, max_length: int = 6) -> str:
        """
        Compute Metaphone key for an English word.
        Translates phonemes into acoustic symbols.
        Example: 'clear' -> 'KLR', 'cleer' -> 'KLR', 'psychology' -> 'SKLJ'
        """
        if not word:
            return ""
        w = TextNormalizer.normalize(word).upper()
        if not w:
            return ""

        length = len(w)
        if length == 0:
            return ""

        # Drop initial silent letters
        if length >= 2:
            if w[:2] in ("KN", "GN", "PN", "AE", "WR", "PS"):
                w = w[1:]
                length = len(w)
            elif w[0] == "X":
                w = "S" + w[1:]
            elif w[:2] == "WH":
                w = "W" + w[2:]
                length = len(w)

        result: List[str] = []
        i = 0

        while i < length and len(result) < max_length:
            c = w[i]
            prev_c = w[i - 1] if i > 0 else ""
            next_c = w[i + 1] if i + 1 < length else ""
            next_next_c = w[i + 2] if i + 2 < length else ""

            # Skip duplicate adjacent letters except 'C'
            if c != "C" and c == prev_c:
                i += 1
                continue

            if c in "AEIOU":
                # Vowels are only encoded if at the beginning of the word
                if i == 0:
                    result.append(c)

            elif c == "B":
                # 'B' is silent if after 'M' at end of word (dumb, lamb)
                if not (i == length - 1 and prev_c == "M"):
                    result.append("B")

            elif c == "C":
                if prev_c == "S" and next_c in ("E", "I", "Y"):
                    pass  # Silent 'c' in 'science'
                elif next_c == "I" and next_next_c == "A":
                    result.append("X")  # 'cia' -> 'sh'
                    i += 1
                elif next_c in ("E", "I", "Y"):
                    result.append("S")
                elif next_c == "H":
                    if next_next_c in ("O", "R", "L") or prev_c in ("S", "K"):
                        result.append("K")
                    else:
                        result.append("X")  # 'ch' -> 'X'
                    i += 1
                else:
                    result.append("K")

            elif c == "D":
                if next_c == "G" and next_next_c in ("E", "I", "Y"):
                    result.append("J")
                    i += 2
                else:
                    result.append("T")

            elif c in ("F", "J", "L", "M", "N", "R"):
                result.append(c)

            elif c == "G":
                if next_c == "H" and not (i + 2 < length and w[i + 2] in "AEIOU"):
                    pass  # Silent 'gh' in 'night', 'through'
                elif next_c == "N" and (i + 2 == length or (i + 3 == length and w[i + 2] == "S")):
                    pass  # Silent 'gn' in 'sign'
                elif next_c in ("E", "I", "Y"):
                    result.append("J")
                else:
                    result.append("K")

            elif c == "H":
                # 'H' is silent if preceded by vowel and not followed by vowel
                if (i == 0 or (prev_c and prev_c in "AEIOU")) and (next_c and next_c in "AEIOU"):
                    result.append("H")

            elif c == "K":
                if prev_c != "C":
                    result.append("K")

            elif c == "P":
                if next_c == "H":
                    result.append("F")
                    i += 1
                else:
                    result.append("P")

            elif c == "Q":
                result.append("K")

            elif c == "S":
                if next_c == "H":
                    result.append("X")
                    i += 1
                elif next_c == "I" and next_next_c in ("O", "A"):
                    result.append("X")
                    i += 1
                else:
                    result.append("S")

            elif c == "T":
                if next_c == "I" and next_next_c in ("O", "A"):
                    result.append("X")
                    i += 1
                elif next_c == "H":
                    result.append("0")  # Theta sound
                    i += 1
                elif next_c == "C" and next_next_c == "H":
                    pass  # 'tch' -> handled by 'ch'
                else:
                    result.append("T")

            elif c == "V":
                result.append("F")

            elif c in ("W", "Y"):
                if next_c and next_c in "AEIOU":
                    result.append(c)

            elif c == "X":
                result.append("K")
                result.append("S")

            elif c == "Z":
                result.append("S")

            i += 1

        return "".join(result)[:max_length]

    @classmethod
    def word_phonetic_similarity(cls, word1: str, word2: str) -> float:
        """
        Calculate phonetic similarity between two words (0.0 to 1.0).
        Evaluates both Metaphone and Soundex representations.
        """
        w1 = TextNormalizer.normalize(word1)
        w2 = TextNormalizer.normalize(word2)

        if not w1 or not w2:
            return 0.0

        if w1 == w2:
            return 1.0

        meta1 = cls.metaphone(w1)
        meta2 = cls.metaphone(w2)
        meta_match = (meta1 == meta2) and (len(meta1) > 0)

        sndx1 = cls.soundex(w1)
        sndx2 = cls.soundex(w2)
        sndx_match = (sndx1 == sndx2) and (len(sndx1) > 0)

        if meta_match and sndx_match:
            return 1.0
        elif meta_match:
            return 0.9
        elif sndx_match:
            return 0.75

        # Check prefix match on metaphone
        if meta1 and meta2 and len(meta1) >= 3 and len(meta2) >= 3:
            if meta1[:3] == meta2[:3]:
                return 0.5

        return 0.0

    @classmethod
    def string_phonetic_similarity(cls, str1: str, str2: str) -> float:
        """
        Calculate phonetic similarity between multi-word strings (e.g. author names).
        Finds best alignment across tokens.
        """
        tokens1 = TextNormalizer.normalize(str1).split()
        tokens2 = TextNormalizer.normalize(str2).split()

        if not tokens1 or not tokens2:
            return 0.0

        total_sim = 0.0
        for t1 in tokens1:
            best = 0.0
            for t2 in tokens2:
                sim = cls.word_phonetic_similarity(t1, t2)
                if sim > best:
                    best = sim
            total_sim += best

        return total_sim / max(len(tokens1), len(tokens2))
