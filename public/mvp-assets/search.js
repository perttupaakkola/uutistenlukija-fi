/* Progressive first-party search. The HTML forms remain site-scoped Google
   searches when this script is unavailable. */
(function () {
  "use strict";

  if (!document.querySelectorAll || !window.URL || !window.URLSearchParams) return;

  var SEARCH_PATH = "/haku/";
  var INDEX_PATH = "/assets/search-index.json";
  var MAX_QUERY_LENGTH = 200;
  var MAX_TERMS = 12;
  var MAX_RESULTS = 20;
  var MAX_INDEX_ITEMS = 5000;
  var ARTICLE_PATH = /^\/uutiset\/[a-z0-9][a-z0-9-]*\/$/;
  var PUBLISHED = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

  function boundedQuery(value) {
    return String(value || "").slice(0, MAX_QUERY_LENGTH).trim();
  }

  function normalize(value) {
    var text = String(value || "").toLowerCase();
    if (text.normalize) text = text.normalize("NFD");
    return text.replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
  }

  function queryTerms(query) {
    var seen = {};
    return normalize(query).split(/\s+/).filter(function (term) {
      if (!term || seen[term]) return false;
      seen[term] = true;
      return true;
    }).slice(0, MAX_TERMS);
  }

  function validEntry(item) {
    if (!item || typeof item !== "object" || Array.isArray(item)) return null;
    var keys = Object.keys(item).sort().join(",");
    if (keys !== "path,published,summary,title") return null;
    if (typeof item.title !== "string" || !item.title.trim() || item.title.length > 500) return null;
    if (typeof item.summary !== "string" || item.summary.length > 2000) return null;
    if (typeof item.path !== "string" || item.path.length > 300 || !ARTICLE_PATH.test(item.path)) return null;
    if (typeof item.published !== "string" || !PUBLISHED.test(item.published)) return null;
    var publishedTime = Date.parse(item.published);
    if (!Number.isFinite(publishedTime)) return null;
    var url;
    try { url = new window.URL(item.path, window.location.origin); } catch (error) { return null; }
    if (url.origin !== window.location.origin || url.pathname !== item.path || url.search || url.hash) return null;
    return {
      title: item.title,
      summary: item.summary,
      path: item.path,
      published: item.published,
      publishedTime: publishedTime,
    };
  }

  function enhanceForms() {
    Array.prototype.forEach.call(document.querySelectorAll("form[data-first-party-action]"), function (form) {
      if (form.getAttribute("data-first-party-action") !== SEARCH_PATH) return;
      form.addEventListener("submit", function (event) {
        var input = form.querySelector('input[name="q"]');
        if (!input) return;
        event.preventDefault();
        window.location.assign(SEARCH_PATH + "?q=" + encodeURIComponent(boundedQuery(input.value)));
      });
    });
  }

  function clearResults(list) {
    while (list.firstChild) list.removeChild(list.firstChild);
  }

  function emptyMessage(list, message, query) {
    var item = document.createElement("li");
    item.className = "search-dropdown__empty";
    var text = document.createElement("span");
    text.textContent = message;
    item.appendChild(text);
    if (query) {
      var strong = document.createElement("strong");
      strong.textContent = query;
      item.appendChild(document.createTextNode(" "));
      item.appendChild(strong);
    }
    list.appendChild(item);
  }

  var dateFormatter = new Intl.DateTimeFormat("fi-FI", {
    timeZone: "Europe/Helsinki",
    day: "numeric",
    month: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  function resultNode(entry) {
    var item = document.createElement("li");
    var link = document.createElement("a");
    var body = document.createElement("span");
    var title = document.createElement("span");
    var meta = document.createElement("span");
    var time = document.createElement("time");
    var summary = document.createElement("span");
    item.className = "search-result";
    link.className = "search-result-item";
    link.setAttribute("href", entry.path);
    body.className = "search-result-item__body";
    title.className = "search-result-item__title";
    title.textContent = entry.title;
    meta.className = "search-result-item__meta";
    time.setAttribute("datetime", entry.published);
    time.textContent = "Julkaistu " + dateFormatter.format(new Date(entry.publishedTime));
    summary.className = "search-result-item__summary";
    summary.textContent = entry.summary;
    meta.appendChild(time);
    body.appendChild(title);
    body.appendChild(meta);
    body.appendChild(summary);
    link.appendChild(body);
    item.appendChild(link);
    return item;
  }

  function renderSearchPage() {
    var input = document.getElementById("search-input");
    var count = document.getElementById("search-count");
    var list = document.getElementById("search-results");
    if (!input || !count || !list) return;

    var query = boundedQuery(new window.URLSearchParams(window.location.search).get("q"));
    input.value = query;
    clearResults(list);
    var terms = queryTerms(query);
    if (!query || !terms.length) {
      count.textContent = "Kirjoita hakusana.";
      return;
    }
    count.textContent = "Haetaan tuloksia…";
    if (typeof window.fetch !== "function") {
      count.textContent = "Hakua ei voida käyttää tässä selaimessa.";
      return;
    }

    window.fetch(INDEX_PATH, { credentials: "same-origin" }).then(function (response) {
      if (!response.ok) throw new Error("search index unavailable");
      return response.json();
    }).then(function (data) {
      if (!Array.isArray(data)) throw new Error("invalid search index");
      var matches = data.slice(0, MAX_INDEX_ITEMS).map(validEntry).filter(function (entry) {
        if (!entry) return false;
        var haystack = normalize(entry.title + " " + entry.summary);
        return terms.every(function (term) { return haystack.indexOf(term) !== -1; });
      }).sort(function (left, right) {
        if (right.publishedTime !== left.publishedTime) return right.publishedTime - left.publishedTime;
        return left.path < right.path ? -1 : (left.path > right.path ? 1 : 0);
      }).slice(0, MAX_RESULTS);

      clearResults(list);
      if (!matches.length) {
        count.textContent = "Ei tuloksia.";
        emptyMessage(list, "Hakusanalla ei löytynyt julkaistuja uutisia:", query);
        return;
      }
      count.textContent = matches.length === 1 ? "1 tulos." : matches.length + " tulosta.";
      matches.forEach(function (entry) { list.appendChild(resultNode(entry)); });
    }).catch(function () {
      clearResults(list);
      count.textContent = "Haku ei ole juuri nyt käytettävissä.";
      emptyMessage(list, "Yritä hetken kuluttua uudelleen.", "");
    });
  }

  enhanceForms();
  renderSearchPage();
})();
