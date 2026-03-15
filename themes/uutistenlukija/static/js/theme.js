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
  
  // Update button icon
  function updateIcon() {
    btn.textContent = html.getAttribute('data-theme') === 'dark' ? '☀️' : '🌙';
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
