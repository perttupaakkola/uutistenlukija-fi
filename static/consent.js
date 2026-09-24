(() => {
  const box = document.getElementById('consent-dialog');
  const open = () => {
    if (!box.open) box.showModal();
    box.focus({ preventScroll: true });
  };
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem('cookie_consent_v2')); } catch (_) {}
  document.getElementById('consent-settings').onclick = open;
  document.getElementById('consent-close').onclick = () => box.close();
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
  if (!saved || saved.v !== 2) open();
})();
