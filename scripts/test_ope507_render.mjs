#!/usr/bin/env node

import assert from 'node:assert/strict';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, resolve, sep } from 'node:path';
import { chromium } from 'playwright';

const publicDir = resolve(process.argv[2] || '');
assert.ok(process.argv[2], 'usage: test_ope507_render.mjs PUBLIC_DIR');
assert.ok(existsSync(publicDir), `missing Hugo output: ${publicDir}`);

const TARGET = '/posts/2026-06-25-raystaspaaskyjen-pesinta-viivastyttaa-hailuodon-lauttojen-si/';
const CONTROL = '/posts/2026-06-29-hailuodon-kiintea-tieyhteys-avautuu-liikenteelle/';
const CANONICAL = 'https://uutistenlukija.fi' + TARGET;
const APPROVED_DESCRIPTION = 'Hailuodon lauttojen siirto viivästyy, sillä lautoilla pesivillä uhanalaisilla räystäspääskyillä on yli sata poikasta.';
const EXPECTED_H1 = 'Räystäspääskyjen pesintä viivästyttää Hailuodon lauttojen siirtoa etelään';
const EXPECTED_FIRST_PARAGRAPH = 'Hailuodon lauttojen siirto etelään lykkääntyy uhanalaisten räystäspääskyjen pesinnän vuoksi. Hailuodon ja Oulunsalon välillä liikennöiviltä lautoilta on löytynyt kymmeniä pesiä, ja poikasia arvioidaan olevan toista sataa. Jos lautat lähtisivät nyt Turkuun, poikaset jäisivät ilman emojen tuomaa ravintoa, koska emot jäisivät Hailuotoon ja Oulunsaloon.';
const MIME = {
  '.css': 'text/css; charset=utf-8',
  '.gif': 'image/gif',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
  '.xml': 'application/xml; charset=utf-8',
};

function browserLaunchOptions() {
  const bundled = chromium.executablePath();
  if (existsSync(bundled)) return { headless: true };
  return { executablePath: '/usr/bin/google-chrome', headless: true };
}

function serveFile(request, response) {
  const pathname = decodeURIComponent(new URL(request.url, 'http://local.test').pathname);
  let filePath = resolve(publicDir, pathname.replace(/^\/+/, ''));
  if (pathname.endsWith('/')) filePath = resolve(filePath, 'index.html');
  if (filePath !== publicDir && !filePath.startsWith(publicDir + sep)) {
    response.writeHead(403).end();
    return;
  }
  if (!existsSync(filePath) || !statSync(filePath).isFile()) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, {
    'cache-control': 'no-store',
    'content-type': MIME[extname(filePath).toLowerCase()] || 'application/octet-stream',
  });
  createReadStream(filePath).pipe(response);
}

function parseColor(value) {
  const match = value.match(/rgba?\(([^)]+)\)/);
  assert(match, `unsupported color: ${value}`);
  return match[1]
    .replace('/', ' ')
    .split(/[\s,]+/)
    .filter(Boolean)
    .slice(0, 3)
    .map(Number);
}

function luminance(rgb) {
  const linear = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(foreground, background) {
  const light = Math.max(luminance(foreground), luminance(background));
  const dark = Math.min(luminance(foreground), luminance(background));
  return (light + 0.05) / (dark + 0.05);
}

async function articleAssertions(browser, origin, viewport, theme) {
  const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
  const page = await context.newPage();
  await page.addInitScript((selectedTheme) => {
    localStorage.setItem('theme', selectedTheme);
  }, theme);
  const response = await page.goto(origin + TARGET, { waitUntil: 'load' });
  assert.equal(response?.status(), 200);
  const renderedTheme = await page.locator('html').getAttribute('data-theme');
  if (theme === 'dark') assert.equal(renderedTheme, 'dark');
  else assert.ok(renderedTheme === null || renderedTheme === 'light');

  const deck = page.locator('[data-ope507-hailuoto-deck="true"]');
  assert.equal(await deck.count(), 1);
  assert.equal(await deck.isVisible(), true);
  assert.equal((await deck.textContent()).trim(), APPROVED_DESCRIPTION);
  const deckState = await deck.evaluate((element) => {
    const style = getComputedStyle(element);
    let surface = element.parentElement;
    while (surface && getComputedStyle(surface).backgroundColor === 'rgba(0, 0, 0, 0)') {
      surface = surface.parentElement;
    }
    return {
      background: surface ? getComputedStyle(surface).backgroundColor : '',
      color: style.color,
      display: style.display,
      lineClamp: style.webkitLineClamp,
      overflow: style.overflow,
      order: Array.from(element.parentElement.children).map((child) => {
        if (child.matches('h1')) return 'h1';
        if (child.matches('[data-ope507-hailuoto-deck]')) return 'deck';
        if (child.matches('.article-hero')) return 'hero';
        return 'other';
      }),
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    };
  });
  assert.equal(deckState.display, 'block');
  assert.notEqual(deckState.overflow, 'hidden');
  assert.notEqual(deckState.lineClamp, '1');
  assert(deckState.scrollWidth <= deckState.clientWidth + 1);
  assert(deckState.order.indexOf('h1') < deckState.order.indexOf('deck'));
  assert(deckState.order.indexOf('deck') < deckState.order.indexOf('hero'));
  assert(contrast(parseColor(deckState.color), parseColor(deckState.background)) >= 4.5);

  assert.equal((await page.locator('h1').textContent()).trim(), EXPECTED_H1);
  assert.equal(await page.locator('link[rel="canonical"]').getAttribute('href'), CANONICAL);
  assert.equal(await page.locator('meta[name="description"]').getAttribute('content'), APPROVED_DESCRIPTION);
  assert.equal(await page.locator('meta[property="og:description"]').getAttribute('content'), APPROVED_DESCRIPTION);
  assert.equal(await page.locator('meta[name="twitter:description"]').getAttribute('content'), APPROVED_DESCRIPTION);
  assert.equal((await page.locator('.content p').first().textContent()).trim(), EXPECTED_FIRST_PARAGRAPH);

  const newsDescriptions = await page.locator('script[type="application/ld+json"]').evaluateAll((scripts) => {
    const descriptions = [];
    for (const script of scripts) {
      let payload;
      try { payload = JSON.parse(script.textContent || '{}'); } catch { continue; }
      const nodes = Array.isArray(payload) ? payload : Array.isArray(payload['@graph']) ? payload['@graph'] : [payload];
      for (const node of nodes) {
        const type = node && node['@type'];
        if (type === 'NewsArticle' || Array.isArray(type) && type.includes('NewsArticle')) {
          descriptions.push(node.description);
        }
      }
    }
    return descriptions;
  });
  assert.deepEqual(newsDescriptions, [APPROVED_DESCRIPTION]);
  await context.close();
}

async function searchAssertions(browser, origin, viewport, theme) {
  const context = await browser.newContext({ viewport, serviceWorkers: 'block' });
  const page = await context.newPage();
  await page.addInitScript((selectedTheme) => {
    localStorage.setItem('theme', selectedTheme);
  }, theme);
  const response = await page.goto(origin + '/haku/?q=Hailuoto', { waitUntil: 'load' });
  assert.equal(response?.status(), 200);
  const results = page.locator('#search-results .search-result');
  await results.first().waitFor({ state: 'visible' });
  assert.equal(await results.count(), 1);
  assert.equal(await results.locator('a.search-result-item').getAttribute('href'), TARGET);
  const summary = results.locator('.search-result-item__summary');
  assert.equal((await summary.textContent()).trim(), APPROVED_DESCRIPTION);
  const state = await summary.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      clientHeight: element.clientHeight,
      lineClamp: style.webkitLineClamp,
      overflow: style.overflow,
      scrollHeight: element.scrollHeight,
    };
  });
  assert(state.scrollHeight <= state.clientHeight + 1);
  assert.notEqual(state.overflow, 'hidden');
  assert.notEqual(state.lineClamp, '1');
  await context.close();
}

const server = createServer(serveFile);
await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));
const address = server.address();
assert(address && typeof address === 'object');
const origin = `http://127.0.0.1:${address.port}`;
const browser = await chromium.launch(browserLaunchOptions());
try {
  for (const viewport of [{ width: 390, height: 844 }, { width: 1366, height: 900 }]) {
    for (const theme of ['light', 'dark']) {
      await articleAssertions(browser, origin, viewport, theme);
      await searchAssertions(browser, origin, viewport, theme);
    }
  }

  const controlPage = await browser.newPage({ serviceWorkers: 'block' });
  await controlPage.goto(origin + CONTROL, { waitUntil: 'load' });
  assert.equal(await controlPage.locator('[data-ope507-hailuoto-deck]').count(), 0);
  await controlPage.close();

  const inflectedPage = await browser.newPage({ serviceWorkers: 'block' });
  await inflectedPage.goto(origin + '/haku/?q=Hailuodon', { waitUntil: 'load' });
  const inflectedResults = inflectedPage.locator('#search-results .search-result');
  await inflectedResults.first().waitFor({ state: 'visible' });
  const inflectedUrls = await inflectedResults.locator('a.search-result-item').evaluateAll(
    (links) => links.map((link) => link.getAttribute('href')),
  );
  assert(inflectedUrls.length >= 2);
  assert.equal(inflectedUrls.filter((url) => url === TARGET).length, 1);
  await inflectedPage.close();
} finally {
  await browser.close();
  await new Promise((resolveClose, rejectClose) => {
    server.close((error) => error ? rejectClose(error) : resolveClose());
  });
}

console.log('OPE-507 production render: 2 viewports x 2 themes article/search + control + Hailuodon — PASS');
