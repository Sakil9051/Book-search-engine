/**
 * Smart Book Search Engine - Frontend Client Script
 * Zero external frameworks. Vanilla JavaScript.
 */

(function () {
  "use strict";

  // DOM Elements
  const searchInput = document.getElementById("search-input");
  const clearBtn = document.getElementById("btn-clear");
  const spinner = document.getElementById("search-spinner");
  const autocompleteList = document.getElementById("autocomplete-list");
  const debugToggle = document.getElementById("debug-toggle");
  const correctionBanner = document.getElementById("correction-banner");
  const correctionText = document.getElementById("correction-text");
  const correctionBadge = document.getElementById("correction-badge");
  const statusBar = document.getElementById("search-status-bar");
  const resultCount = document.getElementById("result-count");
  const displayQuery = document.getElementById("display-query");
  const executionTime = document.getElementById("execution-time");
  const confidenceLevelTag = document.getElementById("confidence-level-tag");
  const resultsGrid = document.getElementById("results-grid");
  const bookModal = document.getElementById("book-modal");
  const modalBody = document.getElementById("modal-body");
  const modalClose = document.getElementById("modal-close");
  const statsBtn = document.getElementById("btn-stats");
  const statsModal = document.getElementById("stats-modal");
  const statsModalClose = document.getElementById("stats-modal-close");

  let debounceTimer = null;
  let currentActiveIndex = -1;
  let lastSearchQuery = "";
  let autocompleteAbortController = null;

  // Initialize
  initEventListeners();

  function initEventListeners() {
    // Search input typing
    searchInput.addEventListener("input", handleInputChange);
    searchInput.addEventListener("keydown", handleKeyNavigation);

    // Clear button
    clearBtn.addEventListener("click", () => {
      searchInput.value = "";
      clearBtn.classList.add("hidden");
      hideAutocomplete();
      resetResults();
      searchInput.focus();
    });

    // Debug toggle change
    debugToggle.addEventListener("change", () => {
      if (searchInput.value.trim().length > 0) {
        performSearch(searchInput.value.trim());
      }
    });

    // Benchmark chips click
    document.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const query = chip.dataset.query;
        searchInput.value = query;
        clearBtn.classList.remove("hidden");
        hideAutocomplete();
        performSearch(query);
      });
    });

    // Outside click to close autocomplete
    document.addEventListener("click", (e) => {
      if (!searchInput.contains(e.target) && !autocompleteList.contains(e.target)) {
        hideAutocomplete();
      }
    });

    // Modals
    modalClose.addEventListener("click", () => bookModal.classList.add("hidden"));
    bookModal.addEventListener("click", (e) => {
      if (e.target === bookModal) bookModal.classList.add("hidden");
    });

    statsBtn.addEventListener("click", openStatsModal);
    statsModalClose.addEventListener("click", () => statsModal.classList.add("hidden"));
    statsModal.addEventListener("click", (e) => {
      if (e.target === statsModal) statsModal.classList.add("hidden");
    });
  }

  function handleInputChange() {
    const query = searchInput.value.trim();

    if (query.length > 0) {
      clearBtn.classList.remove("hidden");
    } else {
      clearBtn.classList.add("hidden");
      if (autocompleteAbortController) {
        autocompleteAbortController.abort();
      }
      hideAutocomplete();
      resetResults();
      return;
    }

    if (query.length < 2) {
      if (autocompleteAbortController) {
        autocompleteAbortController.abort();
      }
      hideAutocomplete();
      return;
    }

    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      fetchAutocomplete(query);
    }, 200);
  }

  function handleKeyNavigation(e) {
    const items = autocompleteList.querySelectorAll(".autocomplete-item");

    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!items.length) return;
      currentActiveIndex = (currentActiveIndex + 1) % items.length;
      updateActiveItem(items);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      currentActiveIndex = (currentActiveIndex - 1 + items.length) % items.length;
      updateActiveItem(items);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (currentActiveIndex >= 0 && items[currentActiveIndex]) {
        items[currentActiveIndex].click();
      } else {
        const query = searchInput.value.trim();
        if (query) {
          hideAutocomplete();
          performSearch(query);
        }
      }
    } else if (e.key === "Escape") {
      hideAutocomplete();
    }
  }

  function updateActiveItem(items) {
    items.forEach((item, idx) => {
      if (idx === currentActiveIndex) {
        item.classList.add("active");
        item.scrollIntoView({ block: "nearest" });
      } else {
        item.classList.remove("active");
      }
    });
  }

  // Highlight matching substring
  function highlightMatch(text, query) {
    if (!text) return "";
    if (!query) return escapeHtml(text);
    const tokens = query
      .trim()
      .split(/\s+/)
      .filter((t) => t.length > 0);
    if (!tokens.length) return escapeHtml(text);

    const escapedTokens = tokens.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const regex = new RegExp(`(${escapedTokens.join("|")})`, "gi");

    const parts = text.split(regex);
    return parts
      .map((part) => {
        if (regex.test(part)) {
          return `<mark class="ac-highlight">${escapeHtml(part)}</mark>`;
        }
        return escapeHtml(part);
      })
      .join("");
  }

  // Autocomplete
  async function fetchAutocomplete(prefix) {
    if (prefix.length < 2) {
      hideAutocomplete();
      return;
    }

    // Cancel / abort previous pending request so older responses cannot overwrite newer results
    if (autocompleteAbortController) {
      autocompleteAbortController.abort();
    }
    autocompleteAbortController = new AbortController();

    // Show loading spinner
    spinner.classList.remove("hidden");

    try {
      const resp = await fetch(`/autocomplete?q=${encodeURIComponent(prefix)}&limit=10`, {
        signal: autocompleteAbortController.signal,
      });

      // Ignore if user has changed input while in-flight
      if (searchInput.value.trim() !== prefix) {
        return;
      }

      if (!resp.ok) return;
      const data = await resp.json();

      // Ensure fresh check
      if (searchInput.value.trim() === prefix) {
        const suggestions = data.suggestions || data.results || [];
        renderAutocomplete(suggestions, prefix);
      }
    } catch (err) {
      if (err.name === "AbortError") {
        // Stale request cancelled normally
        return;
      }
      console.error("Autocomplete error:", err);
    } finally {
      // Hide spinner if not running a full search
      if (!searchInput.value.trim() || searchInput.value.trim() === prefix) {
        spinner.classList.add("hidden");
      }
    }
  }

  function renderAutocomplete(items, query) {
    if (!items || items.length === 0) {
      hideAutocomplete();
      return;
    }

    currentActiveIndex = -1;
    autocompleteList.innerHTML = "";

    // Maximum 10 suggestions
    const topItems = items.slice(0, 10);

    topItems.forEach((item) => {
      const div = document.createElement("div");
      div.className = "autocomplete-item";
      div.setAttribute("role", "option");
      div.setAttribute("tabindex", "-1");

      const displayTitle = item.text || item.title || "";
      const displayAuthor = item.author || item.category || "";
      const itemType = item.type || "book";

      const highlightedTitle = highlightMatch(displayTitle, query);
      const highlightedAuthor = highlightMatch(displayAuthor, query);

      div.innerHTML = `
        <div class="ac-main">
          <span class="ac-title">${highlightedTitle}</span>
          ${displayAuthor ? `<span class="ac-meta">${highlightedAuthor}</span>` : ""}
        </div>
        <span class="ac-badge ${escapeHtml(itemType)}">${escapeHtml(itemType)}</span>
      `;

      // Touch / mouse interaction
      // Use pointerdown with preventDefault to prevent input blur from closing before selection
      const handleSelect = (e) => {
        if (e) e.preventDefault();
        searchInput.value = displayTitle;
        hideAutocomplete();

        // Clicking a suggestion opens the book if it's a book
        if (item.id && itemType !== "author") {
          logClick(query, item.id);
          openBookModal(item.id);
        } else {
          performSearch(displayTitle);
        }
      };

      div.addEventListener("pointerdown", handleSelect);
      div.addEventListener("click", handleSelect);

      autocompleteList.appendChild(div);
    });

    autocompleteList.classList.remove("hidden");
  }

  function hideAutocomplete() {
    autocompleteList.classList.add("hidden");
    autocompleteList.innerHTML = "";
    currentActiveIndex = -1;
  }

  // Full Search
  async function performSearch(query) {
    if (!query) return;

    lastSearchQuery = query;
    spinner.classList.remove("hidden");
    hideAutocomplete();

    const isDebug = debugToggle.checked;

    try {
      const resp = await fetch(`/search?q=${encodeURIComponent(query)}&limit=15&debug=${isDebug}`);
      if (!resp.ok) {
        throw new Error(`Search failed: HTTP ${resp.status}`);
      }
      const data = await resp.json();
      renderSearchResults(data);
    } catch (err) {
      console.error("Search error:", err);
      resultsGrid.innerHTML = `
        <div class="empty-state">
          <h3 class="empty-title">Search Error</h3>
          <p class="empty-text">Could not complete search. Please verify the backend is running.</p>
        </div>
      `;
    } finally {
      spinner.classList.add("hidden");
    }
  }

  function renderSearchResults(data) {
    // Status Bar
    statusBar.classList.remove("hidden");
    resultCount.textContent = data.total_results;
    displayQuery.textContent = data.query;
    executionTime.textContent = `${data.execution_time_ms} ms`;
    confidenceLevelTag.textContent = `${data.correction_level} CONFIDENCE`;

    // Correction Banner ("Did you mean...?")
    if (data.did_you_mean || (data.corrected_query && data.corrected_query !== data.query.toLowerCase())) {
      correctionBanner.classList.remove("hidden");

      let bannerHtml = "";
      if (data.did_you_mean) {
        bannerHtml = `Did you mean: <button class="dym-link" id="btn-dym">${escapeHtml(data.did_you_mean)}</button>?`;
      } else if (data.corrected_query) {
        bannerHtml = `Showing results for: <button class="dym-link" id="btn-dym">${escapeHtml(data.corrected_query)}</button>`;
      }

      correctionText.innerHTML = bannerHtml;
      correctionBadge.className = `confidence-pill ${data.correction_level.toLowerCase()}`;
      correctionBadge.textContent = `${data.correction_confidence}% ${data.correction_level}`;

      const dymBtn = document.getElementById("btn-dym");
      if (dymBtn) {
        dymBtn.addEventListener("click", () => {
          const target = data.did_you_mean || data.corrected_query;
          searchInput.value = target;
          performSearch(target);
        });
      }
    } else {
      correctionBanner.classList.add("hidden");
    }

    // Results List
    if (!data.results || data.results.length === 0) {
      resultsGrid.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              <line x1="8" y1="11" x2="14" y2="11"></line>
            </svg>
          </div>
          <h3 class="empty-title">No matching books found</h3>
          <p class="empty-text">Try different keywords or check out the benchmark test chips above.</p>
        </div>
      `;
      return;
    }

    resultsGrid.innerHTML = "";

    data.results.forEach((book) => {
      const card = document.createElement("div");
      card.className = "book-card";

      // Score class
      let scoreClass = "low";
      if (book.similarity_score >= 90) scoreClass = "high";
      else if (book.similarity_score >= 70) scoreClass = "mid";

      // Stock status
      let stockClass = "in";
      let stockText = `${book.stock} in stock`;
      if (book.stock === 0) {
        stockClass = "out";
        stockText = "Out of stock";
      } else if (book.stock < 10) {
        stockClass = "low";
        stockText = `Only ${book.stock} left`;
      }

      // Matched fields
      const badgesHtml = (book.matched_fields || [])
        .map((f) => {
          let fClass = "";
          if (f.includes("exact")) fClass = "exact";
          else if (f === "alias") fClass = "alias";
          else if (f === "isbn") fClass = "isbn";
          else if (f === "phonetic") fClass = "phonetic";
          return `<span class="field-badge ${fClass}">${escapeHtml(f)}</span>`;
        })
        .join("");

      // Score breakdown (if debug=true)
      let debugHtml = "";
      if (book.score_breakdown) {
        const b = book.score_breakdown;
        debugHtml = `
          <div class="debug-panel">
            <div class="debug-title">Deterministic Ranking Formula Points (Total: ${b.final_raw_score})</div>
            <div class="debug-grid">
              <div class="debug-item"><span>Exact ISBN:</span> <strong>${b.exact_isbn}</strong></div>
              <div class="debug-item"><span>Exact Title:</span> <strong>${b.exact_title}</strong></div>
              <div class="debug-item"><span>Exact Alias:</span> <strong>${b.exact_alias}</strong></div>
              <div class="debug-item"><span>Title Sim:</span> <strong>${b.title_similarity}</strong></div>
              <div class="debug-item"><span>Author Sim:</span> <strong>${b.author_similarity}</strong></div>
              <div class="debug-item"><span>Token Match:</span> <strong>${b.token_match}</strong></div>
              <div class="debug-item"><span>N-Grams:</span> <strong>${b.ngram_similarity}</strong></div>
              <div class="debug-item"><span>Phonetic:</span> <strong>${b.phonetic_similarity}</strong></div>
              <div class="debug-item"><span>Popularity:</span> <strong>${b.popularity}</strong></div>
              <div class="debug-item"><span>Sales:</span> <strong>${b.sales}</strong></div>
            </div>
          </div>
        `;
      }

      card.innerHTML = `
        <div class="card-top">
          <div>
            <h3 class="book-title">${escapeHtml(book.title)}</h3>
            <div class="book-meta-line">
              <span class="book-author">By ${escapeHtml(book.author || "Unknown")}</span>
              <span>•</span>
              <span>${escapeHtml(book.category || "General")}</span>
              <span>•</span>
              <span>ISBN: ${escapeHtml(book.isbn || "N/A")}</span>
            </div>
          </div>
          <div class="score-badge ${scoreClass}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
            </svg>
            ${book.similarity_score}% Match
          </div>
        </div>

        <p class="book-desc">${escapeHtml(book.description || "No description available.")}</p>

        <div class="card-bottom">
          <div class="tags-group">
            <span style="font-size:0.75rem; color:var(--text-light); margin-right:4px;">Matched:</span>
            ${badgesHtml}
          </div>
          <div class="price-stock-group">
            <span class="stock-tag ${stockClass}">${stockText}</span>
            <span class="book-price">$${book.price.toFixed(2)}</span>
          </div>
        </div>

        ${debugHtml}
      `;

      // Click logging & detail modal
      card.addEventListener("click", () => {
        logClick(data.query, book.id);
        openBookModal(book.id);
      });

      resultsGrid.appendChild(card);
    });
  }

  // Click Logging (Search History Learning)
  async function logClick(query, bookId) {
    try {
      await fetch("/search/click", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, book_id: bookId }),
      });
    } catch (err) {
      console.warn("Click logging non-blocking error:", err);
    }
  }

  // Book Detail Modal
  async function openBookModal(bookId) {
    modalBody.innerHTML = `<div style="text-align:center; padding:32px;">Loading book specifications...</div>`;
    bookModal.classList.remove("hidden");

    try {
      const resp = await fetch(`/books/${bookId}`);
      if (!resp.ok) throw new Error("Failed to load book");
      const book = await resp.json();

      const aliasesHtml = (book.aliases || []).length
        ? book.aliases.map((a) => `<span class="field-badge alias">${escapeHtml(a)}</span>`).join(" ")
        : `<span style="color:var(--text-light); font-size:0.8125rem;">No manual aliases registered</span>`;

      modalBody.innerHTML = `
        <h3 class="modal-title">${escapeHtml(book.title)}</h3>
        <p class="modal-subtitle">By ${escapeHtml(book.author || "Unknown")} • Published by ${escapeHtml(book.publisher || "N/A")}</p>

        <div style="margin-bottom: 20px;">
          <h4 style="font-size: 0.8125rem; font-weight:700; text-transform:uppercase; color:var(--text-light); margin-bottom:6px;">Synopsis</h4>
          <p style="font-size: 0.9375rem; color: var(--text-muted); line-height: 1.6;">${escapeHtml(book.description)}</p>
        </div>

        <div class="stats-grid" style="margin-bottom: 20px;">
          <div class="stat-card">
            <span class="stat-num">$${book.price.toFixed(2)}</span>
            <span class="stat-lbl">Price</span>
          </div>
          <div class="stat-card">
            <span class="stat-num">${book.stock}</span>
            <span class="stat-lbl">Stock Units</span>
          </div>
          <div class="stat-card">
            <span class="stat-num">${book.popularity_score}</span>
            <span class="stat-lbl">Popularity</span>
          </div>
          <div class="stat-card">
            <span class="stat-num">${book.sales_count}</span>
            <span class="stat-lbl">Total Sales</span>
          </div>
        </div>

        <div style="margin-bottom: 16px;">
          <h4 style="font-size: 0.8125rem; font-weight:700; text-transform:uppercase; color:var(--text-light); margin-bottom:6px;">Known Aliases & Typo Synonyms</h4>
          <div style="display:flex; flex-wrap:wrap; gap:6px;">
            ${aliasesHtml}
          </div>
        </div>

        <div style="font-family:'JetBrains Mono', monospace; font-size:0.75rem; color:var(--text-light); border-top:1px solid var(--border-color); padding-top:12px;">
          ISBN: ${escapeHtml(book.isbn)} | Normalized Title: ${escapeHtml(book.normalized_title)}
        </div>
      `;
    } catch (err) {
      modalBody.innerHTML = `<div style="color:var(--danger); padding:20px;">Error loading book details.</div>`;
    }
  }

  // Telemetry Modal
  async function openStatsModal() {
    statsModal.classList.remove("hidden");
    const tbody = document.getElementById("recent-logs-body");
    tbody.innerHTML = `<tr><td colspan="3">Fetching live telemetry...</td></tr>`;

    try {
      const resp = await fetch("/stats");
      if (!resp.ok) throw new Error("Failed to fetch stats");
      const data = await resp.json();

      document.getElementById("stat-books").textContent = data.total_books;
      document.getElementById("stat-vocab").textContent = data.vocabulary_entries;
      document.getElementById("stat-aliases").textContent = data.total_aliases;
      document.getElementById("stat-queries").textContent = data.queries_logged;

      if (data.recent_queries && data.recent_queries.length > 0) {
        tbody.innerHTML = data.recent_queries
          .map(
            (q) => `
          <tr>
            <td><strong>${escapeHtml(q.query)}</strong></td>
            <td>${q.result_count} books</td>
            <td>${q.created_at || "Just now"}</td>
          </tr>
        `
          )
          .join("");
      } else {
        tbody.innerHTML = `<tr><td colspan="3">No queries logged yet.</td></tr>`;
      }
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="3" style="color:var(--danger);">Failed to load stats.</td></tr>`;
    }
  }

  function resetResults() {
    statusBar.classList.add("hidden");
    correctionBanner.classList.add("hidden");
    resultsGrid.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path>
            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path>
          </svg>
        </div>
        <h3 class="empty-title">Deterministic Smart Search Ready</h3>
        <p class="empty-text">Enter a title, author name, or deliberately misspell a query above to see the local correction and ranking pipeline in action.</p>
      </div>
    `;
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
})();
