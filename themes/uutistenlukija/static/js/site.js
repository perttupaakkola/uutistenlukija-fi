// site.js — non-critical interactive features (deferred)
(function () {
  'use strict';

  // ── Set --header-h CSS variable for reading-progress bar placement ─────────
  // Progress bar uses top:var(--header-h) so it sits just below the sticky
  // header rather than being hidden behind it.
  function updateHeaderHeight() {
    var h = document.querySelector('.site-header');
    if (h) {
      document.documentElement.style.setProperty('--header-h', h.offsetHeight + 'px');
    }
  }
  updateHeaderHeight();
  window.addEventListener('resize', updateHeaderHeight, { passive: true });

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

  // ── #17: Card shimmer — mark images as loaded, handle errors ──────────────
  document.querySelectorAll('.article-card-thumb, .article-image').forEach(function (img) {
    if (img.complete) {
      img.classList.add('img-loaded');
    } else {
      img.addEventListener('load', function () { img.classList.add('img-loaded'); });
      img.addEventListener('error', function () { img.classList.add('img-loaded'); }); // show even on error
    }
  });

  // ── #18: Sticky header scroll elevation ──────────────────────────────────
  // Add box-shadow when user has scrolled > 4px (signals header is floating)
  var siteHeader = document.querySelector('.site-header');
  if (siteHeader) {
    var SCROLL_ELEV = 4;
    var headerTicking = false;
    window.addEventListener('scroll', function () {
      if (!headerTicking) {
        requestAnimationFrame(function () {
          if (window.scrollY > SCROLL_ELEV) {
            siteHeader.classList.add('header--scrolled');
          } else {
            siteHeader.classList.remove('header--scrolled');
          }
          headerTicking = false;
        });
        headerTicking = true;
      }
    }, { passive: true });
    // Initial state on page load (e.g. back-button restore)
    if (window.scrollY > SCROLL_ELEV) siteHeader.classList.add('header--scrolled');
  }

  // ── #15.1: Category quicknav — highlight active pill on scroll ──────────
  var catPills = document.querySelectorAll('.cat-quicknav__pill[data-cat]');
  if (catPills.length && 'IntersectionObserver' in window) {
    var catSections = document.querySelectorAll('.category-section[id]');
    var activeCat = null;
    var navObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          var id = entry.target.getAttribute('id');  // "cat-kotimaa"
          var slug = id.replace('cat-', '');
          if (activeCat !== slug) {
            activeCat = slug;
            catPills.forEach(function (pill) {
              pill.classList.toggle('is-active', pill.getAttribute('data-cat') === slug);
            });
          }
        }
      });
    }, { rootMargin: '-30% 0px -60% 0px', threshold: 0 });
    catSections.forEach(function (sec) { navObserver.observe(sec); });
  }

})();
