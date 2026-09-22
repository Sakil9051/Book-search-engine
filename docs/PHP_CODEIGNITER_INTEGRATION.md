# PHP / CodeIgniter 4 Integration Guide

This guide documents how the Python deterministic search architecture maps 1-to-1 into a standard **PHP 8.x / CodeIgniter 4** backend without external AI or cloud services.

---

## 1. Architecture Overview

The search engine is designed as a standalone decoupled Service:

```
User Query ("atomic habbits")
  ↓
Normalization (mb_strtolower + iconv ASCII transliteration + regex)
  ↓
ISBN Check (cleanIsbn)
  ↓
Dictionary Spell Correction (levenshtein + jaroWinkler + metaphone)
  ↓
Candidate Generation (MySQL FULLTEXT or SQLite FTS5)
  ↓
Deterministic Ranking Engine (Formula with Configurable Weights)
  ↓
Confidence & Telemetry Logging
```

---

## 2. Database Migration (MySQL / SQLite)

If migrating to **MySQL / MariaDB**:

```sql
-- Books Table
CREATE TABLE books (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    normalized_title VARCHAR(255) NOT NULL,
    author VARCHAR(255) NULL,
    normalized_author VARCHAR(255) NULL,
    isbn VARCHAR(32) NULL UNIQUE,
    description TEXT NULL,
    publisher VARCHAR(255) NULL,
    category VARCHAR(100) NULL,
    price DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    stock INT NOT NULL DEFAULT 0,
    popularity_score FLOAT NOT NULL DEFAULT 0.0,
    sales_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_norm_title (normalized_title),
    INDEX idx_norm_author (normalized_author),
    INDEX idx_isbn (isbn),
    FULLTEXT INDEX ftx_book_search (title, author, description)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Book Aliases Table
CREATE TABLE book_aliases (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    book_id INT UNSIGNED NOT NULL,
    alias VARCHAR(255) NOT NULL,
    normalized_alias VARCHAR(255) NOT NULL,
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_norm_alias (normalized_alias),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Search Dictionary Table
CREATE TABLE search_dictionary (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    word VARCHAR(100) NOT NULL UNIQUE,
    normalized_word VARCHAR(100) NOT NULL,
    frequency INT NOT NULL DEFAULT 1,
    source VARCHAR(50) DEFAULT 'system',
    INDEX idx_norm_word (normalized_word)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Search Telemetry Logs
CREATE TABLE search_logs (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    query VARCHAR(255) NOT NULL,
    normalized_query VARCHAR(255) NOT NULL,
    corrected_query VARCHAR(255) NULL,
    result_count INT NOT NULL DEFAULT 0,
    clicked_book_id INT UNSIGNED NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_norm_query (normalized_query)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

## 3. CodeIgniter 4 Controller Example

File: `app/Controllers/Search.php`

```php
<?php

namespace App\Controllers;

use App\Services\BookSearchService;
use CodeIgniter\API\ResponseTrait;

class Search extends BaseController
{
    use ResponseTrait;

    protected BookSearchService $searchService;

    public function __construct()
    {
        $this->searchService = new BookSearchService();
    }

    /**
     * GET /api/search?q=...&limit=10&debug=false
     */
    public function index()
    {
        $query = $this->request->getGet('q') ?? '';
        $limit = (int)($this->request->getGet('limit') ?? 10);
        $debug = filter_var($this->request->getGet('debug'), FILTER_VALIDATE_BOOLEAN);

        if (empty(trim($query))) {
            return $this->failValidationError('Search query cannot be empty');
        }

        $results = $this->searchService->search($query, $limit, $debug);

        return $this->respond($results);
    }

    /**
     * POST /api/search/click
     */
    public function logClick()
    {
        $json = $this->request->getJSON(true);
        $query = $json['query'] ?? '';
        $bookId = (int)($json['book_id'] ?? 0);

        if (empty($query) || $bookId <= 0) {
            return $this->failValidationError('Valid query and book_id required');
        }

        // Record in search_logs
        $db = \Config\Database::connect();
        $normQuery = $this->searchService->normalizeText($query);

        $db->table('search_logs')
            ->where('normalized_query', $normQuery)
            ->orderBy('created_at', 'DESC')
            ->limit(1)
            ->update(['clicked_book_id' => $bookId]);

        return $this->respond(['status' => 'success', 'message' => 'Click registered']);
    }
}
```

---

## 4. CodeIgniter 4 Routes Definition

File: `app/Config/Routes.php`

```php
$routes->group('api', static function ($routes) {
    $routes->get('search', 'Search::index');
    $routes->post('search/click', 'Search::logClick');
});
```

---

## 5. Performance Optimizations for High Concurrency

1. **Native C Functions**:
   PHP includes native C implementations of `levenshtein()`, `metaphone()`, and `soundex()`. Always use built-in functions rather than userland loops.
2. **Dictionary In-Memory Cache**:
   Use **APCu** or **Redis** to cache the `search_dictionary` word frequencies in memory (`$cache->get('search_dict')`) to avoid hitting SQL on every token.
3. **Database Candidate Pruning**:
   Never run Levenshtein across all rows in MySQL. Always restrict candidate queries using `WHERE MATCH(...) AGAINST(...)` or index-backed `LIKE 'prefix%'` before ranking candidates in PHP memory.
