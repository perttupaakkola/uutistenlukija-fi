(() => {
  const box = document.getElementById('consent-dialog');
  const settings = [...document.querySelectorAll('[data-consent-settings]')];
  let opener = null;
  const controls = () => [...box.querySelectorAll('button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter((element) => !element.disabled && !element.hidden);
  const open = (event) => {
    opener = event && event.currentTarget ? event.currentTarget : null;
    if (!box.open) box.showModal();
    box.focus({ preventScroll: true });
  };
  const close = () => box.close();
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem('cookie_consent_v2')); } catch (_) {}
  settings.forEach((button) => { button.onclick = open; });
  document.getElementById('consent-close').onclick = close;
  document.getElementById('consent-accept').onclick = () => { box.close(); window.newsAnalyticsConsent(true); };
  document.getElementById('consent-reject').onclick = () => {
    for (const cookie of document.cookie.split(';')) {
      const name = cookie.split('=')[0].trim();
      if (/^_ga(?:_|$)/.test(name)) {
        for (const domain of ['', '; Domain=uutistenlukija.fi', '; Domain=.uutistenlukija.fi'])
          document.cookie = name + '=; Max-Age=0; Path=/; SameSite=Lax' + domain;
      }
    }
    box.close(); window.newsAnalyticsConsent(false);
  };
  box.addEventListener('keydown', (event) => {
    if (event.key !== 'Tab') return;
    const items = controls();
    if (!items.length) { event.preventDefault(); box.focus(); return; }
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === box)) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  });
  box.addEventListener('close', () => {
    if (opener && opener.isConnected) opener.focus();
    opener = null;
  });
  if (!saved || saved.v !== 2) open();
})();
