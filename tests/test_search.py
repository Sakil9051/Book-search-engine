"""
Comprehensive Integration Tests for SearchEngine and FastAPI endpoints.
Verifies all benchmark queries, typos, transpositions, author lookups, and ISBN matching.
"""

import pytest
import time
from fastapi.testclient import TestClient

from app.database import init_database
from app.search.engine import SearchEngine
from main import app


@pytest.fixture(scope="module")
def engine():
    conn = init_database(seed_data=True)
    engine_inst = SearchEngine(conn)
    yield engine_inst
    engine_inst.close()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_spell_correction_atomic_habits(engine):
    for query in ["atomic habbits", "atomic habit", "atomik habits"]:
        res = engine.search(query)
        assert len(res.results) > 0
        top_book = res.results[0]
        assert top_book.title == "Atomic Habits"
        assert top_book.similarity_score >= 90.0


def test_spell_correction_harry_potter(engine):
    res = engine.search("harry poter")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert "Harry Potter" in top_book.title
    assert top_book.similarity_score >= 90.0


def test_spell_correction_psychology_of_money(engine):
    for query in ["psychology of mony", "psychology money"]:
        res = engine.search(query)
        assert len(res.results) > 0
        top_book = res.results[0]
        assert top_book.title == "The Psychology of Money"
        assert top_book.similarity_score >= 90.0


def test_missing_letter_alchemist(engine):
    res = engine.search("alchmist")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert top_book.title == "The Alchemist"
    assert top_book.similarity_score >= 90.0


def test_author_phonetic_cleer(engine):
    res = engine.search("james cleer")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert top_book.title == "Atomic Habits"
    assert top_book.author == "James Clear"


def test_author_search_morgan_housel(engine):
    res = engine.search("morgan housel")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert top_book.title == "The Psychology of Money"


def test_extra_letters_rich_dad_poor_dad(engine):
    res = engine.search("rich dad pooor dad")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert top_book.title == "Rich Dad Poor Dad"


def test_missing_word_think_grow_rich(engine):
    res = engine.search("think grow rich")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert top_book.title == "Think and Grow Rich"


def test_word_order_habits_atomic(engine):
    res = engine.search("habits atomic")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert top_book.title == "Atomic Habits"


def test_numeric_alias_7_habits(engine):
    res = engine.search("7 habits highly effective people")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert top_book.title == "The 7 Habits of Highly Effective People"


def test_isbn_exact_search(engine):
    res = engine.search("9780735211292")
    assert len(res.results) > 0
    top_book = res.results[0]
    assert top_book.title == "Atomic Habits"
    assert top_book.similarity_score == 100.0


def test_autocomplete_prefix(engine):
    res = engine.autocomplete("har", limit=10)
    assert len(res.suggestions) > 0
    assert len(res.suggestions) <= 10
    texts = [item.text for item in res.suggestions]
    assert any("Harry Potter" in t for t in texts)


def test_autocomplete_typo_tolerance(engine):
    res = engine.autocomplete("hary pot", limit=10)
    assert len(res.suggestions) > 0
    texts = [item.text for item in res.suggestions]
    assert any("Harry Potter" in t or "Harry Poter" in t for t in texts)


def test_autocomplete_min_chars(engine):
    res = engine.autocomplete("h", limit=10)
    assert len(res.suggestions) == 0


def test_autocomplete_max_10(engine):
    res = engine.autocomplete("a", limit=25)
    assert len(res.suggestions) <= 10


def test_history_learning_click_log(engine):
    # Log user click for a custom query
    query = "greatest habits"
    success = engine.log_click(query, 1)  # Book 1 is Atomic Habits
    assert success is True


def test_search_performance(engine):
    # Measure execution time across a series of queries
    start = time.perf_counter()
    for _ in range(10):
        engine.search("atomic habbits")
    total_elapsed_ms = (time.perf_counter() - start) * 1000.0
    avg_elapsed_ms = total_elapsed_ms / 10.0
    # Average response should be well under 50ms
    assert avg_elapsed_ms < 50.0


# FastAPI HTTP Client Tests
def test_api_search_endpoint(client):
    response = client.get("/search?q=atomic+habbits&debug=true")
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "atomic habbits"
    assert data["corrected_query"] == "atomic habits"
    assert data["total_results"] > 0
    assert data["results"][0]["title"] == "Atomic Habits"
    assert data["results"][0]["score_breakdown"] is not None


def test_api_autocomplete_endpoint(client):
    response = client.get("/autocomplete?q=har&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "har"
    assert "suggestions" in data
    assert len(data["suggestions"]) > 0
    assert len(data["suggestions"]) <= 5
    first = data["suggestions"][0]
    assert "type" in first
    assert "id" in first
    assert "text" in first
    # Backward compatibility
    assert "results" in data
    assert len(data["results"]) > 0


def test_api_autocomplete_typo_query(client):
    response = client.get("/autocomplete?q=hary%20pot")
    assert response.status_code == 200
    data = response.json()
    assert len(data["suggestions"]) > 0
    texts = [item["text"] for item in data["suggestions"]]
    assert any("Harry Potter" in t or "Harry Poter" in t for t in texts)


def test_api_book_detail_endpoint(client):
    response = client.get("/books/1")
    assert response.status_code == 200
    book = response.json()
    assert book["id"] == 1
    assert "Atomic Habits" in book["title"]


def test_api_click_endpoint(client):
    response = client.post(
        "/search/click",
        json={"query": "atomic habbits", "book_id": 1},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_api_stats_endpoint(client):
    response = client.get("/stats")
    assert response.status_code == 200
    stats = response.json()
    assert stats["total_books"] >= 30
    assert stats["vocabulary_entries"] > 100
