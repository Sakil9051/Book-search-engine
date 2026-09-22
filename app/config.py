"""
Search engine configuration and ranking weights.
All parameters can be tuned or overridden via environment variables.
"""

import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "database" / "books.db"

# Database configuration
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH)))

# Debug mode
DEBUG_SEARCH = os.getenv("DEBUG_SEARCH", "false").lower() in ("true", "1", "yes")

# Query limits
MAX_QUERY_LENGTH = int(os.getenv("MAX_QUERY_LENGTH", "150"))
DEFAULT_SEARCH_LIMIT = int(os.getenv("DEFAULT_SEARCH_LIMIT", "20"))
MAX_SEARCH_LIMIT = int(os.getenv("MAX_SEARCH_LIMIT", "50"))
AUTOCOMPLETE_LIMIT = int(os.getenv("AUTOCOMPLETE_LIMIT", "10"))
CANDIDATE_POOL_LIMIT = int(os.getenv("CANDIDATE_POOL_LIMIT", "80"))

# In-memory LRU Cache sizes
SEARCH_CACHE_SIZE = int(os.getenv("SEARCH_CACHE_SIZE", "500"))
AUTOCOMPLETE_CACHE_SIZE = int(os.getenv("AUTOCOMPLETE_CACHE_SIZE", "500"))

# Ranking weights (as requested in Section 19)
EXACT_ISBN_WEIGHT = float(os.getenv("WEIGHT_EXACT_ISBN", "1000.0"))
EXACT_TITLE_WEIGHT = float(os.getenv("WEIGHT_EXACT_TITLE", "950.0"))
EXACT_ALIAS_WEIGHT = float(os.getenv("WEIGHT_EXACT_ALIAS", "900.0"))
EXACT_AUTHOR_WEIGHT = float(os.getenv("WEIGHT_EXACT_AUTHOR", "850.0"))

TITLE_SIMILARITY_MAX = float(os.getenv("WEIGHT_TITLE_SIMILARITY", "800.0"))
AUTHOR_SIMILARITY_MAX = float(os.getenv("WEIGHT_AUTHOR_SIMILARITY", "400.0"))
TOKEN_MATCH_MAX = float(os.getenv("WEIGHT_TOKEN_MATCH", "300.0"))
NGRAM_SIMILARITY_MAX = float(os.getenv("WEIGHT_NGRAM", "200.0"))
PHONETIC_SIMILARITY_MAX = float(os.getenv("WEIGHT_PHONETIC", "100.0"))
POPULARITY_MAX = float(os.getenv("WEIGHT_POPULARITY", "50.0"))
SALES_MAX = float(os.getenv("WEIGHT_SALES", "50.0"))

# Confidence thresholds (Section 20)
# Score >= 90: HIGH (automatically use corrected search)
# 70-89: MEDIUM (show "Did you mean: ...?")
# < 70: LOW (do not automatically correct)
CONFIDENCE_HIGH = 90.0
CONFIDENCE_MEDIUM = 70.0
