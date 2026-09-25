/* Shell behaviour only: the mobile menu and the reader's theme choice.
   No analytics, no third-party scripts, no network requests. */
(function () {
  "use strict";
  var root = document.documentElement;
  var STORAGE_KEY = "uutistenlukija-theme";
  var DARK_QUERY = "(prefers-color-scheme: dark)";

  function storedTheme() {
    try {
      var value = window.localStorage.getItem(STORAGE_KEY);
      return value === "dark" || value === "light" ? value : null;
    } catch (error) {
      return null;
    }
  }

  function systemTheme() {
    return window.matchMedia && window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
  }

  /* Resolve before any interaction: an explicit choice wins, otherwise the OS
     preference applies, so the theme tokens and the ported sheet agree on first
     paint instead of half-switching. */
  var theme = storedTheme() || systemTheme();
  root.setAttribute("data-theme", theme);
  root.style.colorScheme = theme;

  var themeToggles = [
    document.getElementById("theme-toggle"),
    document.getElementById("theme-toggle-menu"),
  ].filter(function (button) { return button; });

  function syncThemeControls(value) {
    themeToggles.forEach(function (button) {
      button.setAttribute("aria-pressed", value === "dark" ? "true" : "false");
      button.setAttribute("aria-label", value === "dark" ? "Vaihda vaaleaan teemaan" : "Vaihda tummaan teemaan");
    });
  }

  syncThemeControls(theme);
  themeToggles.forEach(function (button) {
    button.addEventListener("click", function () {
      var current = root.getAttribute("data-theme") || systemTheme();
      var next = current === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      root.style.colorScheme = next;
      syncThemeControls(next);
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch (error) {
        /* Storage unavailable: the choice still applies for this page view. */
      }
    });
  });

  var menuButton = document.getElementById("hamburger");
  var nav = document.getElementById("main-nav-menu");
  if (menuButton && nav) {
    var setOpen = function (open) {
      nav.classList.toggle("nav-open", open);
      menuButton.setAttribute("aria-expanded", open ? "true" : "false");
      menuButton.setAttribute("aria-label", open ? "Sulje valikko" : "Avaa valikko");
    };
    menuButton.addEventListener("click", function () {
      setOpen(!nav.classList.contains("nav-open"));
    });
  }

  var search = document.getElementById("header-search");
  var searchToggle = document.getElementById("header-search-toggle");
  var searchInput = document.getElementById("header-search-input");
  if (search && searchToggle && searchInput) {
    var setSearchOpen = function (open, focusInput) {
      search.classList.toggle("site-search--collapsed", !open);
      searchToggle.setAttribute("aria-expanded", open ? "true" : "false");
      searchToggle.setAttribute("aria-label", open ? "Sulje haku" : "Avaa haku");
      if (open && focusInput) searchInput.focus();
    };
    setSearchOpen(!search.classList.contains("site-search--collapsed"), false);
    searchToggle.addEventListener("click", function () {
      setSearchOpen(search.classList.contains("site-search--collapsed"), true);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (!search.classList.contains("site-search--collapsed")) {
        setSearchOpen(false, false);
        searchToggle.focus();
      }
      if (nav && nav.classList.contains("nav-open")) {
        nav.classList.remove("nav-open");
        if (menuButton) {
          menuButton.setAttribute("aria-expanded", "false");
          menuButton.setAttribute("aria-label", "Avaa valikko");
          menuButton.focus();
        }
      }
    });
  } else {
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav && nav.classList.contains("nav-open")) {
        nav.classList.remove("nav-open");
        if (menuButton) {
          menuButton.setAttribute("aria-expanded", "false");
          menuButton.setAttribute("aria-label", "Avaa valikko");
          menuButton.focus();
        }
      }
    });
  }
})();

/* Refresh only the original header forecast and existing market panel. */
(function () {
  'use strict';
  var source = document.getElementById('frontpage-data');
  if (!source) return;
  var data;
  try { data = JSON.parse(source.textContent); } catch (_) { return; }
  function fiDate(raw) {
    return new Intl.DateTimeFormat('fi-FI', { timeZone: 'Europe/Helsinki', day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(raw));
  }
  function update() {
    var now = Date.now(), weather = data.helsinki || {};
    var age = now - Date.parse(weather.updated_at);
    var hour = (weather.hours || []).reduce(function (best, item) {
      return !best || Math.abs(Date.parse(item.time) - now) < Math.abs(Date.parse(best.time) - now) ? item : best;
    }, null);
    var value = document.getElementById('weather-value'), time = document.getElementById('weather-time');
    if (value && time) {
      var detail = 'Sääennuste ei ole nyt saatavilla.';
      if (hour && age >= 0 && age <= 18 * 3600000 && Math.abs(Date.parse(hour.time) - now) <= 5400000) {
        value.textContent = Math.round(hour.temperature) + ' °C';
        time.textContent = 'Helsinki · ennuste';
        detail = 'Ennuste ' + fiDate(hour.time) + ' · päivitetty ' + fiDate(weather.updated_at) + ' · MET Norway, CC BY 4.0';
      } else {
        value.textContent = '-- °C';
        time.textContent = 'Helsinki · sää ei saatavilla';
      }
      var surface = value.closest('.portal-weather');
      surface.title = detail;
      surface.setAttribute('aria-label', value.textContent + ', ' + time.textContent + '. ' + detail);
    }
    var market = data.markets || {}, values = document.getElementById('market-values'), label = document.getElementById('market-time');
    var marketAge = Math.floor(now / 86400000) - Math.floor(Date.parse(market.date) / 86400000);
    if (values && label && !(marketAge >= 0 && marketAge <= 7)) {
      values.textContent = '';
      label.textContent = 'Valuuttakurssit eivät ole nyt saatavilla.';
    }
  }
  update();
  setInterval(update, 60000);
})();
