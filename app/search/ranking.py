"""
Deterministic multi-component search ranking engine.
Calculates candidate relevance using configurable weights without AI models.
"""

import math
from typing import Dict, List, Optional, Set, Tuple
from app import config
from app.models.book import ScoreBreakdown
from app.search.fuzzy import FuzzyMatcher
from app.search.ngram import NgramMatcher
from app.search.normalizer import TextNormalizer
from app.search.phonetic import PhoneticMatcher
from app.search.tokenizer import Tokenizer


class RankingEngine:
    """
    Ranks book search candidates based on exact, fuzzy, phonetic, token,
    and business popularity signals.
    """

    @classmethod
    def score_candidate(
        cls,
        candidate: dict,
        query: str,
        corrected_query: str,
        debug: bool = False,
    ) -> Tuple[float, float, List[str], Optional[ScoreBreakdown]]:
        """
        Compute total ranking score for a book candidate against a user query.
        Returns:
            (raw_score, normalized_similarity_score_100, matched_fields, score_breakdown)
        """
        norm_query = TextNormalizer.normalize(query)
        norm_corrected = TextNormalizer.normalize(corrected_query)
        clean_isbn_query = TextNormalizer.clean_isbn(query)

        norm_title = candidate.get("normalized_title", "")
        norm_author = candidate.get("normalized_author", "")
        cand_isbn = TextNormalizer.clean_isbn(candidate.get("isbn"))
        aliases: List[str] = candidate.get("aliases", [])

        matched_fields: List[str] = []
        breakdown = ScoreBreakdown() if debug else None

        raw_score = 0.0

        # 1. Exact ISBN Match (Weight: 1000)
        if clean_isbn_query and cand_isbn and clean_isbn_query == cand_isbn:
            exact_isbn_pts = config.EXACT_ISBN_WEIGHT
            raw_score += exact_isbn_pts
            matched_fields.append("isbn")
            if breakdown:
                breakdown.exact_isbn = exact_isbn_pts

        # 2. Exact Title Match (Weight: 950)
        if norm_query == norm_title or (norm_corrected and norm_corrected == norm_title):
            exact_title_pts = config.EXACT_TITLE_WEIGHT
            raw_score += exact_title_pts
            matched_fields.append("exact_title")
            if breakdown:
                breakdown.exact_title = exact_title_pts

        # 3. Exact Alias Match (Weight: 900)
        alias_matched = False
        for alias in aliases:
            norm_alias = TextNormalizer.normalize(alias)
            if norm_alias in (norm_query, norm_corrected):
                exact_alias_pts = config.EXACT_ALIAS_WEIGHT
                raw_score += exact_alias_pts
                matched_fields.append("alias")
                alias_matched = True
                if breakdown:
                    breakdown.exact_alias = exact_alias_pts
                break

        # 4. Exact Author Match (Weight: 850)
        if norm_author and (norm_query == norm_author or norm_corrected == norm_author):
            exact_auth_pts = config.EXACT_AUTHOR_WEIGHT
            raw_score += exact_auth_pts
            matched_fields.append("exact_author")
            if breakdown:
                breakdown.exact_author = exact_auth_pts

        # 5. Title Similarity (0 - 800)
        # Check against both original query and spell-corrected query
        sim_orig = FuzzyMatcher.string_similarity(norm_query, norm_title)
        sim_corr = FuzzyMatcher.string_similarity(norm_corrected, norm_title) if norm_corrected else 0.0
        best_title_sim = max(sim_orig, sim_corr)

        # Contained title boost (e.g. "harry potter" inside "harry potter and the philosopher's stone")
        if norm_query in norm_title or (norm_corrected and norm_corrected in norm_title):
            # Ratio of query length to title length
            coverage = min(1.0, len(norm_query) / max(1, len(norm_title)))
            contained_boost = 0.85 + (0.15 * coverage)
            best_title_sim = max(best_title_sim, contained_boost)

        title_pts = best_title_sim * config.TITLE_SIMILARITY_MAX
        raw_score += title_pts
        if best_title_sim >= 0.70 and "exact_title" not in matched_fields:
            matched_fields.append("fuzzy_title")
        if breakdown:
            breakdown.title_similarity = round(title_pts, 2)

        # 6. Author Similarity (0 - 400)
        if norm_author:
            auth_sim_orig = FuzzyMatcher.string_similarity(norm_query, norm_author)
            auth_sim_corr = FuzzyMatcher.string_similarity(norm_corrected, norm_author) if norm_corrected else 0.0
            best_auth_sim = max(auth_sim_orig, auth_sim_corr)

            if norm_query in norm_author or (norm_corrected and norm_corrected in norm_author):
                best_auth_sim = max(best_auth_sim, 0.90)

            auth_pts = best_auth_sim * config.AUTHOR_SIMILARITY_MAX
            raw_score += auth_pts
            if best_auth_sim >= 0.70 and "exact_author" not in matched_fields:
                matched_fields.append("author")
            if breakdown:
                breakdown.author_similarity = round(auth_pts, 2)

        # 7. Token Match Score (0 - 300)
        # Split query and target into significant words and test stem equality
        query_tokens = Tokenizer.tokenize(norm_corrected or norm_query)
        sig_query_tokens = Tokenizer.filter_stop_words(query_tokens) or query_tokens
        cand_tokens = Tokenizer.tokenize(f"{norm_title} {norm_author}")
        cand_stems = set(Tokenizer.stem_tokens(cand_tokens))

        matched_token_count = 0
        for qt in sig_query_tokens:
            q_stem = Tokenizer.stem(qt)
            if q_stem in cand_stems or any(FuzzyMatcher.word_similarity(qt, ct) >= 0.85 for ct in cand_tokens):
                matched_token_count += 1

        token_ratio = matched_token_count / max(1, len(sig_query_tokens))
        token_pts = token_ratio * config.TOKEN_MATCH_MAX
        raw_score += token_pts
        if token_ratio >= 0.75:
            matched_fields.append("tokens")
        if breakdown:
            breakdown.token_match = round(token_pts, 2)

        # 8. Character N-Gram Similarity (0 - 200)
        ngram_sim = NgramMatcher.similarity(norm_corrected or norm_query, norm_title)
        ngram_pts = ngram_sim * config.NGRAM_SIMILARITY_MAX
        raw_score += ngram_pts
        if breakdown:
            breakdown.ngram_similarity = round(ngram_pts, 2)

        # 9. Phonetic Matching (0 - 100)
        phon_score = 0.0
        if norm_author:
            # Check author phonetic match (e.g. 'cleer' -> 'clear', 'housel' -> 'housel')
            auth_phon = PhoneticMatcher.string_phonetic_similarity(norm_query, norm_author)
            phon_score = max(phon_score, auth_phon)

        # Check title phonetic match
        title_phon = PhoneticMatcher.string_phonetic_similarity(norm_query, norm_title)
        phon_score = max(phon_score, title_phon * 0.75)

        phonetic_pts = phon_score * config.PHONETIC_SIMILARITY_MAX
        raw_score += phonetic_pts
        if phon_score >= 0.80 and "author" not in matched_fields and "exact_author" not in matched_fields:
            matched_fields.append("phonetic")
        if breakdown:
            breakdown.phonetic_similarity = round(phonetic_pts, 2)

        # 10. Popularity Score (0 - 50)
        pop_raw = float(candidate.get("popularity_score") or 0.0)
        pop_normalized = min(1.0, pop_raw / 100.0)
        pop_pts = pop_normalized * config.POPULARITY_MAX
        raw_score += pop_pts
        if breakdown:
            breakdown.popularity = round(pop_pts, 2)

        # 11. Sales Count (0 - 50)
        sales_raw = int(candidate.get("sales_count") or 0)
        # Logarithmic dampening so a bestseller doesn't disproportionately distort matches
        sales_factor = min(1.0, math.log10(sales_raw + 1) / 4.0)
        sales_pts = sales_factor * config.SALES_MAX
        raw_score += sales_pts
        if breakdown:
            breakdown.sales = round(sales_pts, 2)

        if breakdown:
            breakdown.final_raw_score = round(raw_score, 2)

        # Deduplicate matched_fields
        unique_matched_fields = list(dict.fromkeys(matched_fields))
        if not unique_matched_fields:
            unique_matched_fields = ["title"]

        # Calculate a human-interpretable similarity percentage (0.0 to 100.0)
        # If exact ISBN or exact Title: 98 - 100%
        if clean_isbn_query and cand_isbn and clean_isbn_query == cand_isbn:
            sim_percent = 100.0
        elif norm_query == norm_title:
            sim_percent = 99.5
        elif norm_corrected == norm_title:
            sim_percent = 96.5
        elif alias_matched:
            sim_percent = 95.0
        else:
            # Blend title similarity, token match, and author similarity
            base_ratio = (
                (0.55 * best_title_sim) +
                (0.25 * token_ratio) +
                (0.10 * ngram_sim) +
                (0.10 * (best_auth_sim if norm_author else 0.0))
            )
            sim_percent = min(96.0, max(10.0, base_ratio * 100.0))

        return raw_score, round(sim_percent, 1), unique_matched_fields, breakdown
