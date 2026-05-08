const CACHE_NAME = 'uutistenlukija-v3';
const OFFLINE_URL = '/offline.html';
const PRECACHE = ['/', OFFLINE_URL];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

function isFrontendAsset(request) {
  return request.destination === 'style' || request.destination === 'script';
}

function cacheableResponse(response) {
  return response && response.ok && response.type !== 'opaque';
}

function networkFirst(request) {
  return caches.open(CACHE_NAME).then(cache =>
    fetch(request).then(response => {
      if (cacheableResponse(response)) {
        cache.put(request, response.clone());
      }
      return response;
    }).catch(() => cache.match(request))
  );
}

self.addEventListener('fetch', event => {
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() =>
        caches.match(OFFLINE_URL)
      )
    );
  } else if (isFrontendAsset(event.request)) {
    event.respondWith(networkFirst(event.request));
  }
});
