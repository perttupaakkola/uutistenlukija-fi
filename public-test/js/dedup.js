/**
 * dedup.js — Client-side cross-widget article deduplication
 *
 * Problem: Hugo template dedup (server-side) prevents duplicate articles
 * within sections, but JS-rendered widgets (most-read, trending) load
 * independently and may re-surface articles already visible on the page.
 *
 * Solution:
 *   1. On DOMContentLoaded: scan all rendered article links and register them.
 *      Hide any exact-href duplicates that appear more than once in the DOM.
 *   2. Expose window.ArticleDedup.registerArticle(href) → boolean
 *      Widgets call this before rendering an item. Returns true if the article
 *      is NOT a duplicate (safe to show), false if already seen (skip it).
 *
 * Usage in widgets:
 *   if (!window.ArticleDedup || window.ArticleDedup.registerArticle(href)) {
 *     // render the item
 *   }
 *
 * No external dependencies. Safe to load async/defer.
 */

(function (global) {
  'use strict';

  var seen = new Set();

  function normalise(href) {
    try {
      var url = new URL(href, global.location.href);
      var path = url.pathname.replace(/\/+$/, '');
      return url.origin + path;
    } catch (e) {
      return href.split('#')[0].replace(/\/+$/, '');
    }
  }

  function registerArticle(href) {
    var key = normalise(href);
    if (seen.has(key)) { return false; }
    seen.add(key);
    return true;
  }

  function scanDOM() {
    var selectors = [
      'article a[href]', '.article-card a[href]', '.hero-link[href]',
      '.highlight-link[href]', '.lyhyet-link[href]', '.related-link[href]',
      '.most-read-link[href]', '.tila-recent-link[href]',
    ];
    document.querySelectorAll(selectors.join(', ')).forEach(function (link) {
      var href = link.getAttribute('href');
      if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) return;
      if (!registerArticle(href)) {
        var card = link.closest('article, .article-card, .highlight-item, .lyhyet-item, .related-item, .most-read-item, li');
        var target = card || link;
        target.setAttribute('aria-hidden', 'true');
        target.style.display = 'none';
      }
    });
  }

  var ArticleDedup = {
    registerArticle: registerArticle,
    scan: scanDOM,
    seen: function () { return Array.from(seen); },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scanDOM);
  } else {
    scanDOM();
  }

  global.ArticleDedup = ArticleDedup;
}(typeof window !== 'undefined' ? window : this));
