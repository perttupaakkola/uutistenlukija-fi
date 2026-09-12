/* Template for reviewed PUBLIC pages only; never linked by private previews. */
(() => {
  'use strict';
  const id = 'G-35XERS8V6J', key = 'cookie_consent_v2';
  window['ga-disable-' + id] = true;
  let loaded = false;
  function apply() {
    let prefs = null;
    try { prefs = JSON.parse(localStorage.getItem(key)); } catch (_) {}
    const allowed = location.origin === 'https://uutistenlukija.fi' &&
      prefs && prefs.v === 2 && prefs.analytics === true;
    window['ga-disable-' + id] = !allowed;
    if (!allowed || loaded) return;
    loaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', id, {anonymize_ip: true});
    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + id;
    document.head.appendChild(s);
  }
  window.newsAnalyticsConsent = function (allowed) {
    // Preserve the existing preference schema. Advertising remains off.
    try { localStorage.setItem(key, JSON.stringify({v:2, necessary:true, analytics:allowed===true, advertising:false})); }
    catch (_) { window['ga-disable-' + id] = true; return; }
    if (!allowed) { window['ga-disable-' + id] = true; location.reload(); return; }
    apply();
  };
  apply();
})();
