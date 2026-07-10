(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root && root.document) api.boot(root);
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  function normalizedConfig(config) {
    var immutableActivationFloor = 3;
    var rawRevision = config && config.configuredConsentRevision !== undefined ?
      config.configuredConsentRevision : config && config.consentRevision;
    var rawActivationRevision = config && config.activationRevision;
    var revision = rawRevision === undefined || rawRevision === null || rawRevision === '' ?
      2 : Number(rawRevision);
    var activationRevision = rawActivationRevision === undefined || rawActivationRevision === null || rawActivationRevision === '' ?
      immutableActivationFloor : Number(rawActivationRevision);
    if (!Number.isInteger(revision)) revision = 0;
    if (!Number.isInteger(activationRevision)) activationRevision = 0;
    var enabled = !!(config && config.enabled);
    var providerId = String((config && config.providerId) || '').trim();
    var activationRequested = enabled && !!providerId;
    var activationFloorValid = activationRevision >= immutableActivationFloor;
    var currentConsentRevision = activationRequested ?
      Math.max(revision, immutableActivationFloor) : 2;
    return {
      enabled: enabled,
      providerId: providerId,
      configuredConsentRevision: revision,
      consentRevision: currentConsentRevision,
      activationRevision: activationRevision,
      immutableActivationFloor: immutableActivationFloor,
      activationRequested: activationRequested,
      activationFloorValid: activationFloorValid
    };
  }

  function evaluateAccess(config, prefs) {
    var current = normalizedConfig(config);
    var providerReady = current.activationRequested && current.activationFloorValid &&
      current.configuredConsentRevision >= current.immutableActivationFloor &&
      current.configuredConsentRevision >= current.activationRevision;
    var currentChoice = !!prefs && Number(prefs.v) === current.consentRevision;
    return {
      providerReady: providerReady,
      currentChoice: currentChoice,
      shouldReprompt: current.activationRequested && !currentChoice,
      mayLoad: providerReady && currentChoice && prefs.advertising === true
    };
  }

  function createRuntime(root, config) {
    var document = root.document;
    var loaded = false;

    function appendHint(rel) {
      var link = document.createElement('link');
      link.rel = rel;
      link.href = 'https://pagead2.googlesyndication.com';
      if (rel === 'preconnect') link.crossOrigin = 'anonymous';
      document.head.appendChild(link);
    }

    function hydrateSlots(current) {
      var slots = [];
      Array.prototype.forEach.call(
        document.querySelectorAll('script[data-ul-ad-slot-intent]'),
        function (intent) {
          var payload;
          try { payload = JSON.parse(intent.textContent || '{}'); } catch (error) { payload = {}; }
          var position = String(payload.position || '').trim();
          if (!position) return;

          var container = document.createElement('div');
          container.className = 'ad-slot ad-slot-' + position;
          var slot = document.createElement('ins');
          slot.className = 'adsbygoogle';
          slot.style.display = 'block';
          slot.style.textAlign = 'center';
          slot.setAttribute('data-ad-layout', 'in-article');
          slot.setAttribute('data-ad-format', 'fluid');
          slot.setAttribute('data-ad-client', current.providerId);
          slot.setAttribute('data-ad-slot', position);
          container.appendChild(slot);
          intent.parentNode.insertBefore(container, intent.nextSibling);
          slots.push(slot);
        }
      );
      return slots;
    }

    function loadProvider(current, slots) {
      var script = document.createElement('script');
      script.async = true;
      script.crossOrigin = 'anonymous';
      script.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=' +
        encodeURIComponent(current.providerId);
      script.addEventListener('load', function () {
        root.adsbygoogle = root.adsbygoogle || [];
        slots.forEach(function () { root.adsbygoogle.push({}); });
      });
      document.head.appendChild(script);
    }

    function applyConsent(prefs) {
      var current = normalizedConfig(config);
      var decision = evaluateAccess(config, prefs);
      if (!decision.mayLoad || loaded) return decision;

      loaded = true;
      appendHint('preconnect');
      appendHint('dns-prefetch');
      var slots = hydrateSlots(current);
      loadProvider(current, slots);
      return decision;
    }

    return { applyConsent: applyConsent, evaluateAccess: evaluateAccess };
  }

  function boot(root) {
    var script = root.document.querySelector('script[data-ul-ad-runtime]');
    if (!script) return null;
    var config = {
      enabled: script.dataset.enabled === 'true',
      providerId: script.dataset.providerId || '',
      consentRevision: Number(script.dataset.consentRevision || 0),
      activationRevision: Number(script.dataset.activationRevision || 3)
    };
    var runtime = createRuntime(root, config);
    root.UutistenlukijaAds = runtime;
    if (root.__UL_AD_CONSENT__) runtime.applyConsent(root.__UL_AD_CONSENT__);
    return runtime;
  }

  return {
    boot: boot,
    createRuntime: createRuntime,
    evaluateAccess: evaluateAccess,
    normalizedConfig: normalizedConfig
  };
});
