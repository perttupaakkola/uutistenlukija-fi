(function() {
  const btn = document.getElementById('theme-toggle');
  const html = document.documentElement;
  
  // Load saved preference or use system preference
  const saved = localStorage.getItem('theme');
  if (saved) {
    html.setAttribute('data-theme', saved);
  } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    html.setAttribute('data-theme', 'dark');
  }
  
  const icon = btn.querySelector('.theme-toggle-icon');
  const label = btn.querySelector('.theme-toggle-label');

  // Update button icon and label
  function updateIcon() {
    const isDark = html.getAttribute('data-theme') === 'dark';
    icon.textContent = isDark ? '☀️' : '🌙';
    label.textContent = isDark ? 'Vaalea' : 'Tumma';
  }
  updateIcon();
  
  btn.addEventListener('click', function() {
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateIcon();
  });
})();
