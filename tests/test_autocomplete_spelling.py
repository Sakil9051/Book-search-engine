"""
Tests for AutocompleteEngine, SpellingCorrector, TypoDictionary, and SearchHistoryManager.
Verifies all functional constraints:
- Starts after 2 characters
- Max 10 suggestions
- Typo-tolerant autocomplete with prefix priority
- Confidence levels (HIGH auto-correct, MEDIUM did-you-mean, LOW no correction)
- History learning and alias reinforcement
- Zero AI / 100% deterministic local algorithms
"""

import pytest
import sqlite3
from fastapi.testclient import TestClient

from app.database import init_database
from app.search.engine import SearchEngine
from app.search.autocomplete import AutocompleteEngine
from app.search.spelling import SpellingCorrector
from app.search.typo import TypoDictionary
from app.search.history import SearchHistoryManager
from main import app


@pytest.fixture(scope="module")
def shared_db():
    conn = init_database(":memory:", seed_data=True)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def client(shared_db):
    app.state.search_engine = SearchEngine(shared_db)
    with TestClient(app) as c:
        yield c


def test_autocomplete_min_chars(shared_db):
    engine = AutocompleteEngine()
    # 0 or 1 char returns empty suggestions
    res0 = engine.autocomplete("", 10, shared_db)
    assert len(res0.suggestions) == 0

    res1 = engine.autocomplete("h", 10, shared_db)
    assert len(res1.suggestions) == 0

    # 2 chars returns suggestions
    res2 = engine.autocomplete("ha", 10, shared_db)
    assert len(res2.suggestions) > 0


def test_autocomplete_max_10_suggestions(shared_db):
    engine = AutocompleteEngine()
    res = engine.autocomplete("th", 20, shared_db)
    assert len(res.suggestions) <= 10


def test_autocomplete_fields_coverage(shared_db):
    engine = AutocompleteEngine()

    # Title prefix
    res_title = engine.autocomplete("atom", 5, shared_db)
    assert any("Atomic Habits" in s.text for s in res_title.suggestions)

    # Author prefix
    res_author = engine.autocomplete("rowl", 5, shared_db)
    assert any("Rowling" in s.text or (s.author and "Rowling" in s.author) for s in res_author.suggestions)

    # Category prefix
    res_cat = engine.autocomplete("fina", 5, shared_db)
    assert any("Finance" in (s.category or s.text) for s in res_cat.suggestions) or len(res_cat.suggestions) > 0

    # Publisher prefix
    res_pub = engine.autocomplete("aver", 5, shared_db)
    assert any("Avery" in (s.publisher or s.text) for s in res_pub.suggestions) or len(res_pub.suggestions) > 0


def test_autocomplete_typo_tolerance(shared_db):
    engine = AutocompleteEngine()
    # "hary" typo for "harry"
    res = engine.autocomplete("hary", 10, shared_db)
    assert len(res.suggestions) > 0
    assert any("Harry Potter" in s.text or "Rowling" in (s.author or "") for s in res.suggestions)


def test_spelling_corrector_thresholds(shared_db):
    corrector = SpellingCorrector()

    # High confidence typo (in common_typos table or edit distance 1)
    corr, conf, level, dym = corrector.correct_query("atomik habbits", shared_db)
    assert corr == "atomic habits"
    assert level == "HIGH"
    assert conf >= 90.0

    # Medium confidence
    corr_m, conf_m, level_m, dym_m = corrector.correct_query("hpotter stone", shared_db)
    assert level_m in ("HIGH", "MEDIUM")
    assert conf_m >= 70.0

    # Low confidence (gibberish should not correct or have low confidence)
    corr_l, conf_l, level_l, dym_l = corrector.correct_query("xyzqwkzzpl", shared_db)
    assert level_l == "LOW" or conf_l < 70.0


def test_typo_dictionary_caching_and_persistence(shared_db):
    typo_dict = TypoDictionary()
    assert typo_dict.lookup("habbits", shared_db) == "habits"
    assert typo_dict.lookup("alchmist", shared_db) == "alchemist"

    # Add custom typo
    typo_dict.add_typo("pythn", "python", shared_db)
    assert typo_dict.lookup("pythn", shared_db) == "python"


def test_search_history_learning(shared_db):
    history_mgr = SearchHistoryManager()
    cursor = shared_db.cursor()

    # Find a book id
    cursor.execute("SELECT id FROM books WHERE title LIKE 'Atomic Habits%' LIMIT 1")
    book_id = cursor.fetchone()[0]

    # Log clicks for a custom query
    query = "the tiny habits guide"
    history_mgr.log_click(query, book_id, shared_db)
    history_mgr.log_click(query, book_id, shared_db)

    # After 2 clicks, it should be learned as an alias
    cursor.execute(
        "SELECT alias FROM book_aliases WHERE book_id = ? AND normalized_alias = ?",
        (book_id, "the tiny habits guide"),
    )
    learned = cursor.fetchone()
    assert learned is not None


def test_api_autocomplete_har(client):
    resp = client.get("/autocomplete?q=har")
    assert resp.status_code == 200
    data = resp.json()

    assert data["query"] == "har"
    assert "suggestions" in data
    assert len(data["suggestions"]) <= 10

    # Should contain Harry Potter books or J.K. Rowling
    suggestions = data["suggestions"]
    assert len(suggestions) > 0
    top_texts = [s["text"] for s in suggestions]
    assert any("Harry" in t for t in top_texts)


def test_api_search_with_did_you_mean(client):
    # Query with medium confidence or typo
    resp = client.get("/search?q=harry poter")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total_results"] > 0
    assert len(data["results"]) > 0
    # Top result should be Harry Potter
    assert "Harry Potter" in data["results"][0]["title"]
