# OPE-19 parked weather/context UI drift patch

Generated: 2026-05-06T13:40:00Z

Decision: park, not ship. This captures the partial weather/context UI implementation before cleanup from the primary worktree.

Reason: public UI touches header/base template/service worker/CSS/JS and needs clean-worktree browser review before deploy.

Tracked diff before parking:
```diff
diff --git a/layouts/_default/baseof.html b/layouts/_default/baseof.html
index 0f3442aa3..39ea5f087 100644
--- a/layouts/_default/baseof.html
+++ b/layouts/_default/baseof.html
@@ -117,6 +117,7 @@
   {{ partial "cookie-banner.html" . }}
   {{ partial "analytics.html" . }}
   {{ partial "event-tracking.html" . }}
+  <script defer src="/js/weather.js"></script>
   <script defer src="/js/search.js"></script>
   <script>
   // Register service worker after page markup is parsed.
diff --git a/layouts/partials/header.html b/layouts/partials/header.html
index e7fced1e7..7e258c798 100644
--- a/layouts/partials/header.html
+++ b/layouts/partials/header.html
@@ -21,9 +21,9 @@
     </div>
 
     <div class="portal-actions" aria-label="Pikatoiminnot">
-      <span class="portal-weather" aria-label="Sää Helsingissä">
+      <span class="portal-weather" aria-label="Sää Helsingissä" data-weather-widget data-weather-location="Helsinki" title="Ladataan säätä…">
         <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="27" height="27" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
-        <span><strong>18 °C</strong><small>Helsinki</small></span>
+        <span class="portal-weather__text"><strong data-weather-temp>— °C</strong><small data-weather-label>Helsinki</small></span>
       </span>
       <a class="portal-action portal-action--desktop" href="/paivan-tarkeimmat-uutiset/"><span class="portal-live-dot" aria-hidden="true"></span>Live</a>
       <a class="portal-action portal-action--desktop" href="/tila/">
diff --git a/static/_worker.js b/static/_worker.js
index 6a34ff066..c4deda53e 100644
--- a/static/_worker.js
+++ b/static/_worker.js
@@ -1,4 +1,6 @@
 const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
+const WEATHER_ENDPOINT = 'https://api.met.no/weatherapi/locationforecast/2.0/compact';
+const WEATHER_USER_AGENT = 'Uutistenlukija/1.0 https://uutistenlukija.fi';
 
 function jsonResponse(body, status = 200) {
   return new Response(JSON.stringify(body), {
@@ -126,6 +128,88 @@ async function sendWelcomeEmail(env, email) {
   return response.json();
 }
 
+function weatherResponse(body, status = 200, cacheSeconds = 900) {
+  return new Response(JSON.stringify(body), {
+    status,
+    headers: {
+      'content-type': 'application/json; charset=UTF-8',
+      'cache-control': `public, max-age=${cacheSeconds}, s-maxage=${cacheSeconds}`,
+    },
+  });
+}
+
+function pickWeatherSymbol(series) {
+  return (
+    series?.data?.next_1_hours?.summary?.symbol_code ||
+    series?.data?.next_6_hours?.summary?.symbol_code ||
+    series?.data?.next_12_hours?.summary?.symbol_code ||
+    ''
+  );
+}
+
+async function handleWeather(request, env) {
+  if (request.method !== 'GET') {
+    return jsonResponse({ ok: false, error: 'method_not_allowed' }, 405);
+  }
+
+  const url = new URL(request.url);
+  const lat = Number(url.searchParams.get('lat') || env?.WEATHER_LAT || '60.1699');
+  const lon = Number(url.searchParams.get('lon') || env?.WEATHER_LON || '24.9384');
+  const altitude = Number(url.searchParams.get('altitude') || env?.WEATHER_ALTITUDE || '16');
+  const location = String(url.searchParams.get('location') || env?.WEATHER_LOCATION || 'Helsinki').trim().slice(0, 80);
+
+  if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(altitude)) {
+    return jsonResponse({ ok: false, error: 'invalid_coordinates' }, 400);
+  }
+
+  const upstreamUrl = new URL(WEATHER_ENDPOINT);
+  upstreamUrl.searchParams.set('lat', String(lat));
+  upstreamUrl.searchParams.set('lon', String(lon));
+  upstreamUrl.searchParams.set('altitude', String(altitude));
+
+  try {
+    const upstream = await fetch(upstreamUrl.toString(), {
+      headers: {
+        'User-Agent': WEATHER_USER_AGENT,
+        'Accept': 'application/json',
+      },
+      cf: { cacheTtl: 900, cacheEverything: true },
+    });
+
+    if (!upstream.ok) {
+      const errorText = await upstream.text();
+      throw new Error(`MET weather failed (${upstream.status}): ${errorText}`);
+    }
+
+    const data = await upstream.json();
+    const series = data?.properties?.timeseries?.[0];
+    const details = series?.data?.instant?.details;
+
+    if (!series || !details || typeof details.air_temperature !== 'number') {
+      throw new Error('MET weather payload missing current temperature');
+    }
+
+    return weatherResponse({
+      ok: true,
+      location,
+      updated_at: data?.properties?.meta?.updated_at || null,
+      observed_at: series.time,
+      temperature_c: Math.round(details.air_temperature),
+      temperature_c_exact: details.air_temperature,
+      symbol_code: pickWeatherSymbol(series),
+      precipitation_next_1h_mm: series?.data?.next_1_hours?.details?.precipitation_amount ?? null,
+      wind_speed_mps: details.wind_speed ?? null,
+    });
+  } catch (error) {
+    console.error('weather fetch failed', error);
+    return weatherResponse(
+      { ok: false, error: 'weather_unavailable', message: 'Säätietoja ei saatu juuri nyt.' },
+      502,
+      60,
+    );
+  }
+}
+
 async function handleSubscribe(request, env) {
   if (request.method !== 'POST') {
     return jsonResponse({ ok: false, error: 'method_not_allowed' }, 405);
@@ -188,6 +272,10 @@ export default {
       return handleSubscribe(request, env, ctx);
     }
 
+    if (url.pathname === '/api/weather') {
+      return handleWeather(request, env, ctx);
+    }
+
     return env.ASSETS.fetch(request);
   },
 };
diff --git a/static/css/portal-overhaul.css b/static/css/portal-overhaul.css
index cdc75023d..666980e05 100644
--- a/static/css/portal-overhaul.css
+++ b/static/css/portal-overhaul.css
@@ -96,7 +96,9 @@ main.container { padding-top: 0; padding-bottom: 48px; }
 .portal-search .search-toggle-btn { display: none !important; }
 .portal-actions { justify-self: end; display: flex; align-items: center; gap: 22px; color: var(--portal-ink); font-size: 15px; font-weight: 760; white-space: nowrap; }
 .portal-weather { display: inline-flex; gap: 10px; align-items: center; }
-.portal-weather span { display: grid; gap: 2px; }
+.portal-weather.is-loading { opacity: .72; }
+.portal-weather__text { display: grid; gap: 2px; }
+.portal-weather strong { min-width: 3.8ch; }
 .portal-weather small { font-size: 12px; color: var(--portal-muted); font-weight: 600; }
 .portal-action { display: inline-flex; gap: 7px; align-items: center; }
 .portal-live-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--portal-red); }
```

Untracked static/js/weather.js before parking:
```js
(function () {
  'use strict';

  var widget = document.querySelector('[data-weather-widget]');
  if (!widget) return;

  var tempEl = widget.querySelector('[data-weather-temp]');
  var labelEl = widget.querySelector('[data-weather-label]');
  var defaultLocation = widget.getAttribute('data-weather-location') || 'Helsinki';

  function setFallback(message) {
    widget.classList.remove('is-loading');
    if (tempEl) tempEl.textContent = '— °C';
    if (labelEl) labelEl.textContent = defaultLocation;
    widget.setAttribute('title', message || ('Sää: ' + defaultLocation));
  }

  function symbolLabel(symbolCode) {
    if (!symbolCode) return '';
    var base = String(symbolCode).replace(/_(day|night|polartwilight)$/i, '');
    var labels = {
      clearsky: 'Selkeää',
      fair: 'Melko selkeää',
      partlycloudy: 'Puolipilvistä',
      cloudy: 'Pilvistä',
      lightrain: 'Heikkoa sadetta',
      rain: 'Sadetta',
      heavyrain: 'Runsasta sadetta',
      lightrainshowers: 'Sadekuuroja',
      rainshowers: 'Sadekuuroja',
      heavyrainshowers: 'Voimakkaita kuuroja',
      sleet: 'Räntää',
      snow: 'Lumisadetta',
      fog: 'Sumua'
    };
    return labels[base] || '';
  }

  widget.classList.add('is-loading');

  fetch('/api/weather', { headers: { Accept: 'application/json' } })
    .then(function (response) {
      if (!response.ok) throw new Error('weather ' + response.status);
      return response.json();
    })
    .then(function (data) {
      if (!data || !data.ok || typeof data.temperature_c !== 'number') {
        throw new Error('invalid weather payload');
      }

      var location = data.location || defaultLocation;
      var condition = symbolLabel(data.symbol_code);
      if (tempEl) tempEl.textContent = data.temperature_c + ' °C';
      if (labelEl) labelEl.textContent = condition ? (location + ' · ' + condition) : location;
      widget.setAttribute('title', condition ? ('Sää Helsingissä: ' + data.temperature_c + ' °C, ' + condition) : ('Sää Helsingissä: ' + data.temperature_c + ' °C'));
      widget.classList.remove('is-loading');
    })
    .catch(function () {
      setFallback('Säätietoja ei saatu juuri nyt.');
    });
})();
```

Untracked tmp-weather-preview-server.mjs before cleanup:
```js
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { createReadStream, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import worker from './static/_worker.js';

const root = '/tmp/uutistenlukija-weather-check';
const mime = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.js', 'application/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.xml', 'application/xml; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.ico', 'image/x-icon'],
  ['.txt', 'text/plain; charset=utf-8'],
  ['.webp', 'image/webp']
]);

function sendFile(res, filePath) {
  const ext = path.extname(filePath).toLowerCase();
  res.writeHead(200, { 'content-type': mime.get(ext) || 'application/octet-stream' });
  createReadStream(filePath).pipe(res);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1:4173');

  if (url.pathname === '/api/weather') {
    const request = new Request(url.toString(), { method: req.method, headers: req.headers });
    const response = await worker.fetch(request, { ASSETS: { fetch: () => new Response('not found', { status: 404 }) } });
    res.writeHead(response.status, Object.fromEntries(response.headers.entries()));
    res.end(await response.text());
    return;
  }

  let filePath = path.join(root, decodeURIComponent(url.pathname));
  if (url.pathname.endsWith('/')) filePath = path.join(root, url.pathname, 'index.html');
  else if (!path.extname(filePath)) {
    const asDir = path.join(root, url.pathname, 'index.html');
    if (existsSync(asDir)) filePath = asDir;
  }
  if (!existsSync(filePath)) {
    const fallback = path.join(root, '404.html');
    if (existsSync(fallback)) {
      res.writeHead(404, { 'content-type': 'text/html; charset=utf-8' });
      res.end(await readFile(fallback));
    } else {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('Not found');
    }
    return;
  }
  sendFile(res, filePath);
});

server.listen(4173, '127.0.0.1', () => {
  console.log('preview server listening on http://127.0.0.1:4173');
});
```
