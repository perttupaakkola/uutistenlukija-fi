// theme.js — dark/light toggle
// NOTE: theme is applied before first paint via inline script in baseof.html.
// This file handles the toggle button UI + OS preference changes.
(function () {
  'use strict';

  var btn = document.getElementById('theme-toggle');
  if (!btn) return;

  var html = document.documentElement;
  var icon = btn.querySelector('.theme-toggle-icon');
  var label = btn.querySelector('.theme-toggle-label');

  function applyToggleUI(isDark) {
    if (icon) icon.textContent = isDark ? '☀️' : '🌙';
    if (label) label.textContent = isDark ? 'Vaalea' : 'Tumma';
    btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
  }

  // Sync UI with current theme (set by inline head script)
  var isDark = html.getAttribute('data-theme') === 'dark';
  applyToggleUI(isDark);

  // Toggle on click
  btn.addEventListener('click', function () {
    var nowDark = html.getAttribute('data-theme') === 'dark';
    var newTheme = nowDark ? 'light' : 'dark';
    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    applyToggleUI(!nowDark);
  });

  // React to OS-level changes (only when user hasn't manually chosen)
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
      if (!localStorage.getItem('theme')) {
        var sysTheme = e.matches ? 'dark' : 'light';
        html.setAttribute('data-theme', sysTheme);
        applyToggleUI(e.matches);
      }
    });
  }
})();
