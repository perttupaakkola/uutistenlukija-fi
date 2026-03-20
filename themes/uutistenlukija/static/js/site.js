// site.js — non-critical interactive features (deferred)
(function () {
  'use strict';

  // ── Mobile sticky header: hide on scroll-down, show on scroll-up ──────────
  // Applies only to viewports < 768px. Desktop unchanged.
  var header = document.querySelector('.site-header');
  if (header) {
    var lastScrollY = window.scrollY;
    var ticking = false;
    var THRESHOLD = 60; // px before we start hiding
    var MOBILE_BP = 768;

    window.addEventListener('scroll', function () {
      if (!ticking) {
        requestAnimationFrame(function () {
          var currentScrollY = window.scrollY;
          if (window.innerWidth < MOBILE_BP) {
            if (currentScrollY > lastScrollY && currentScrollY > THRESHOLD) {
              header.classList.add('header--hidden');
            } else {
              header.classList.remove('header--hidden');
            }
          } else {
            // Always visible on desktop
            header.classList.remove('header--hidden');
          }
          lastScrollY = currentScrollY;
          ticking = false;
        });
        ticking = true;
      }
    }, { passive: true });
  }

  // ── Back to top button ────────────────────────────────────────────────────
  var backToTop = document.getElementById('back-to-top');
  if (backToTop) {
    window.addEventListener('scroll', function () {
      if (window.scrollY > 400) {
        backToTop.classList.add('visible');
      } else {
        backToTop.classList.remove('visible');
      }
    }, { passive: true });

    backToTop.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // ── Reading progress bar ──────────────────────────────────────────────────
  var progressBar = document.querySelector('.reading-progress');
  if (progressBar) {
    window.addEventListener('scroll', function () {
      var scrollTop = window.scrollY;
      var docHeight = document.documentElement.scrollHeight - window.innerHeight;
      var progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
      progressBar.style.width = Math.min(progress, 100) + '%';
    }, { passive: true });
  }

  // ── Hamburger nav toggle ──────────────────────────────────────────────────
  var hamburger = document.querySelector('.hamburger-btn');
  var mainNav = document.querySelector('.main-nav');
  if (hamburger && mainNav) {
    hamburger.addEventListener('click', function () {
      var isOpen = mainNav.classList.toggle('nav-open');
      hamburger.classList.toggle('is-open', isOpen);
      hamburger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      // When opening, focus first nav link for keyboard users
      if (isOpen) {
        var firstLink = mainNav.querySelector('a');
        if (firstLink) firstLink.focus();
      }
    });

    // Close nav when a link is clicked
    mainNav.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        mainNav.classList.remove('nav-open');
        hamburger.classList.remove('is-open');
        hamburger.setAttribute('aria-expanded', 'false');
      });
    });

    // Close nav on Escape key
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && mainNav.classList.contains('nav-open')) {
        mainNav.classList.remove('nav-open');
        hamburger.classList.remove('is-open');
        hamburger.setAttribute('aria-expanded', 'false');
        hamburger.focus();
      }
    });
  }

  // ── TOC toggle ───────────────────────────────────────────────────────────
  var tocToggle = document.querySelector('.toc-toggle');
  var tocList = document.querySelector('.toc-list');
  var tocArrow = document.querySelector('.toc-arrow');
  if (tocToggle && tocList) {
    tocToggle.addEventListener('click', function () {
      var collapsed = tocList.classList.toggle('toc-collapsed');
      if (tocArrow) tocArrow.textContent = collapsed ? '▶' : '▼';
      tocToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });
  }

  // ── Load more articles ───────────────────────────────────────────────────
  var loadMoreBtn = document.querySelector('.load-more-btn');
  if (loadMoreBtn) {
    var BATCH = 12;
    loadMoreBtn.addEventListener('click', function () {
      var hidden = document.querySelectorAll('.hidden-article');
      var toShow = Array.prototype.slice.call(hidden, 0, BATCH);
      toShow.forEach(function (el) { el.classList.remove('hidden-article'); });
      var remaining = document.querySelectorAll('.hidden-article').length;
      if (remaining === 0) {
        loadMoreBtn.parentElement.remove();
      } else {
        var countEl = loadMoreBtn.querySelector('.load-more-count');
        if (countEl) countEl.textContent = '(' + remaining + ')';
      }
    });
  }

  // ── Lazy image loading (IntersectionObserver) ─────────────────────────────
  if ('IntersectionObserver' in window) {
    var imgObserver = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var img = entry.target;
          if (img.dataset.src) {
            img.src = img.dataset.src;
            img.removeAttribute('data-src');
          }
          img.classList.add('loaded');
          obs.unobserve(img);
        }
      });
    }, { rootMargin: '200px' });

    document.querySelectorAll('img[data-src]').forEach(function (img) {
      imgObserver.observe(img);
    });
  }

  // ── Hero image loaded class ───────────────────────────────────────────────
  document.querySelectorAll('.article-hero-img').forEach(function (img) {
    if (img.complete) {
      img.classList.add('loaded');
    } else {
      img.addEventListener('load', function () { img.classList.add('loaded'); });
    }
  });

})();
