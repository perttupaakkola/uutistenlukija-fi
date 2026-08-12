(function () {
  'use strict';

  var INDEX_URL = '/search-index.json';
  var MAX_HEADER_RESULTS = 8;
  var MAX_PAGE_RESULTS = 20;
  var indexPromise = null;
  var categoryNames = {
    kotimaa: 'Kotimaa',
    ulkomaat: 'Ulkomaat',
    talous: 'Talous',
    teknologia: 'Teknologia',
    urheilu: 'Urheilu',
    kulttuuri: 'Kulttuuri',
    tiede: 'Tiede',
    oppaat: 'Oppaat'
  };
  var ARTICLE_SEARCH_ALIASES_BY_URL = {
    '/posts/2026-06-25-raystaspaaskyjen-pesinta-viivastyttaa-hailuodon-lauttojen-si/': ['Hailuoto']
  };

  function esc(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function normalize(value) {
    return String(value || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .trim();
  }

  function formatDate(iso) {
    if (!iso) return '';
    try {
      return new Intl.DateTimeFormat('fi-FI', {
        day: 'numeric',
        month: 'numeric',
        year: 'numeric'
      }).format(new Date(iso));
    } catch (err) {
      return iso;
    }
  }

  function categoryLabel(category) {
    var slug = normalize(category);
    return categoryNames[slug] || category || '';
  }

  function categoryClass(category) {
    return 'result-cat result-cat--' + normalize(category);
  }

  function prepareItem(item, aliasesByUrl) {
    var title = String(item.title || '');
    var summary = String(item.summary || item.description || '');
    var category = String(item.category || '');
    var url = String(item.url || item.slug || item.permalink || '#');
    var publishedAt = String(item.published_at || item.date || item.publishedAt || '');
    var searchTerms = Array.isArray(item.search_terms)
      ? item.search_terms.join(' ')
      : String(item.search_terms || '');
    var aliasMap = aliasesByUrl || ARTICLE_SEARCH_ALIASES_BY_URL;
    var searchAliases = Array.isArray(aliasMap[url]) ? aliasMap[url].join(' ') : '';
    return {
      title: title,
      slug: url,
      category: category,
      summary: summary,
      published_at: publishedAt,
      haystack: normalize([title, summary, category, searchTerms, searchAliases].join(' '))
    };
  }

  function ensureIndex() {
    if (!indexPromise) {
      indexPromise = fetch(INDEX_URL)
        .then(function (response) {
          if (!response.ok) throw new Error('search-index ' + response.status);
          return response.json();
        })
        .then(function (items) {
          return (items || []).map(function (item) {
            return prepareItem(item);
          });
        });
    }
    return indexPromise;
  }

  function rankResults(items, query) {
    var terms = normalize(query).split(/\s+/).filter(Boolean);
    if (!terms.length) return [];

    return items
      .map(function (item, idx) {
        var score = 0;
        var titleNorm = normalize(item.title);
        var summaryNorm = normalize(item.summary);
        var allMatched = terms.every(function (term) {
          var matched = item.haystack.indexOf(term) !== -1;
          if (!matched) return false;
          if (titleNorm.indexOf(term) !== -1) score += 6;
          if (summaryNorm.indexOf(term) !== -1) score += 3;
          if (item.haystack.indexOf(term) === 0) score += 2;
          return true;
        });
        if (!allMatched) return null;
        if (titleNorm.indexOf(normalize(query)) !== -1) score += 10;
        return { item: item, score: score, idx: idx };
      })
      .filter(Boolean)
      .sort(function (a, b) {
        if (b.score !== a.score) return b.score - a.score;
        return a.idx - b.idx;
      })
      .map(function (entry) { return entry.item; });
  }

  function resultMarkup(item) {
    var category = categoryLabel(item.category);
    var categoryHtml = category
      ? '<span class="' + categoryClass(item.category) + '">' + esc(category) + '</span>'
      : '';

    return '<a class="search-result-item" href="' + esc(item.slug) + '">' +
      '<span class="search-result-item__body">' +
      '<span class="search-result-item__title">' + esc(item.title) + '</span>' +
      '<span class="search-result-item__meta">' +
      categoryHtml +
      '<span class="search-result-item__date">' + esc(formatDate(item.published_at)) + '</span>' +
      '</span>' +
      (item.summary
        ? '<span class="search-result-item__summary">' + esc(item.summary) + '</span>'
        : '') +
      '</span>' +
      '</a>';
  }

  function initHeaderSearch(root) {
    var form = root.querySelector('[data-search-form]');
    var input = root.querySelector('[data-search-input]');
    var panel = root.querySelector('[data-search-dropdown]');
    var status = root.querySelector('[data-search-status]');
    if (!form || !input || !panel || !status) return;

    var toggle = root.querySelector('[data-search-toggle]');
    var lastResults = [];

    function expandSearch(focusInput) {
      root.classList.remove('site-search--collapsed');
      root.classList.add('site-search--expanded');
      if (toggle) toggle.setAttribute('aria-expanded', 'true');
      if (focusInput) {
        window.setTimeout(function () { input.focus(); }, 0);
      }
    }

    function collapseSearch() {
      root.classList.add('site-search--collapsed');
      root.classList.remove('site-search--expanded');
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
    }

    function closeDropdown() {
      root.classList.remove('is-open');
      panel.hidden = true;
      status.textContent = '';
    }

    function openDropdown() {
      expandSearch(false);
      root.classList.add('is-open');
      panel.hidden = false;
    }

    function render(items, query) {
      if (!query || query.length < 2) {
        closeDropdown();
        panel.innerHTML = '';
        return;
      }

      if (!items.length) {
        openDropdown();
        status.textContent = 'Ei osumia';
        panel.innerHTML = '<div class="search-dropdown__empty">Ei hakutuloksia haulla <br><strong>“' + esc(query) + '”</strong>.</div>';
        return;
      }

      lastResults = items.slice(0, MAX_HEADER_RESULTS);
      openDropdown();
      status.textContent = lastResults.length + ' tulosta';
      panel.innerHTML = lastResults.map(resultMarkup).join('');
    }

    function runSearch(query) {
      if (!query || query.trim().length < 2) {
        closeDropdown();
        panel.innerHTML = '';
        return;
      }

      status.textContent = 'Ladataan…';
      ensureIndex()
        .then(function (items) {
          render(rankResults(items, query), query.trim());
        })
        .catch(function (err) {
          console.error('Header search failed:', err);
          openDropdown();
          status.textContent = 'Haku ei ole käytettävissä';
          panel.innerHTML = '<div class="search-dropdown__empty">Hakuhakemiston lataus epäonnistui.</div>';
        });
    }

    if (toggle) {
      toggle.setAttribute('aria-expanded', 'false');
      toggle.addEventListener('click', function () {
        expandSearch(true);
      });
    }

    var debounce;
    input.addEventListener('input', function () {
      var value = input.value;
      window.clearTimeout(debounce);
      debounce = window.setTimeout(function () {
        runSearch(value);
      }, 120);
    });

    input.addEventListener('focus', function () {
      if (input.value.trim().length >= 2 && panel.innerHTML.trim()) {
        openDropdown();
      }
    });

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      var query = input.value.trim();
      if (!query) {
        window.location.href = '/haku/';
        return;
      }
      window.location.href = '/haku/?q=' + encodeURIComponent(query);
    });

    document.addEventListener('click', function (event) {
      if (!root.contains(event.target)) {
        closeDropdown();
        if (!input.value.trim()) collapseSearch();
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        closeDropdown();
        input.blur();
        if (!input.value.trim()) collapseSearch();
      }
    });
  }

  function initSearchPage() {
    var page = document.querySelector('[data-search-page]');
    if (!page) return;

    var input = page.querySelector('#search-input');
    var count = page.querySelector('#search-count');
    var results = page.querySelector('#search-results');
    if (!input || !count || !results) return;

    function updateUrl(query) {
      try {
        var url = new URL(window.location.href);
        if (query) url.searchParams.set('q', query);
        else url.searchParams.delete('q');
        window.history.replaceState({}, '', url.toString());
      } catch (err) {}
    }

    function render(items, query) {
      if (!query || query.length < 2) {
        count.textContent = '';
        results.innerHTML = '';
        return;
      }

      if (!items.length) {
        count.textContent = '';
        results.innerHTML = 
          '<div class="empty-state">' +
            '<div class="empty-state__icon">' +
              '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:100%; height:100%"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>' +
            '</div>' +
            '<h2 class="empty-state__title">Ei hakutuloksia</h2>' +
            '<p class="empty-state__description">Haulla &ldquo;' + esc(query) + '&rdquo; ei löytynyt osumia. Kokeile eri hakusanoja tai selaa uutisaiheita alta.</p>' +
            '<div class="empty-state__actions">' +
              '<a href="/" class="empty-state__btn empty-state__btn--primary">Palaa etusivulle</a>' +
              '<a href="/categories/" class="empty-state__btn empty-state__btn--secondary">Selaa kategorioita</a>' +
            '</div>' +
          '</div>';
        return;
      }

      var shown = items.slice(0, MAX_PAGE_RESULTS);
      count.textContent = shown.length + ' tulosta';
      results.innerHTML = shown.map(function (item) {
        return '<div class="search-result" role="listitem">' + resultMarkup(item) + '</div>';
      }).join('');
    }

    function runSearch(query) {
      query = (query || '').trim();
      updateUrl(query);
      if (query.length < 2) {
        render([], '');
        return;
      }
      results.innerHTML = '<div class="search-loading">Ladataan…</div>';
      ensureIndex()
        .then(function (items) {
          render(rankResults(items, query), query);
        })
        .catch(function (err) {
          console.error('Search page failed:', err);
          count.textContent = '';
          results.innerHTML = '<div class="no-results">Hakuindeksin lataus epäonnistui.</div>';
        });
    }

    var debounce;
    input.addEventListener('input', function () {
      var value = input.value;
      window.clearTimeout(debounce);
      debounce = window.setTimeout(function () {
        runSearch(value);
      }, 120);
    });

    page.querySelector('form[role="search"]').addEventListener('submit', function (event) {
      event.preventDefault();
      runSearch(input.value);
    });

    window.addEventListener('popstate', function () {
      var params = new URLSearchParams(window.location.search);
      var query = params.get('q') || '';
      input.value = query;
      runSearch(query);
    });

    var initialQuery = '';
    try {
      initialQuery = new URLSearchParams(window.location.search).get('q') || '';
    } catch (err) {}
    if (initialQuery) {
      input.value = initialQuery;
      runSearch(initialQuery);
    }
  }

  if (typeof module === 'object' && module.exports) {
    module.exports = {
      ARTICLE_SEARCH_ALIASES_BY_URL: ARTICLE_SEARCH_ALIASES_BY_URL,
      normalize: normalize,
      prepareItem: prepareItem,
      rankResults: rankResults
    };
    return;
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-site-search]').forEach(initHeaderSearch);
    initSearchPage();
  });
})();
