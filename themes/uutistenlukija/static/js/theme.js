// theme.js — dark/light toggle
// NOTE: theme is applied before first paint via inline script in baseof.html.
// This file only handles the toggle button UI.
(function () {
  'use strict';

  var btn = document.getElementById('theme-toggle');
  if (!btn) return;

  var html = document.documentElement;
  var icon = btn.querySelector('.theme-toggle-icon');
  var label = btn.querySelector('.theme-toggle-label');

  function updateIcon() {
    var isDark = html.getAttribute('data-theme') === 'dark';
    if (icon) icon.textContent = isDark ? '☀️' : '🌙';
    if (label) label.textContent = isDark ? 'Vaalea' : 'Tumma';
    btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
  }

  updateIcon();

  btn.addEventListener('click', function () {
    var current = html.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateIcon();
  });
})();
