#!/usr/bin/env node
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { chromium } from 'playwright';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const GA_ID = 'G-TEST123';
const ANALYTICS_HOSTS = new Set([
  'www.googletagmanager.com',
  'region1.google-analytics.com',
  'www.google-analytics.com',
  'stats.g.doubleclick.net',
]);

function browserLaunchOptions() {
  const bundled = chromium.executablePath();
  if (existsSync(bundled)) return { headless: true };
  return { executablePath: '/usr/bin/google-chrome', headless: true };
}

function renderConsentPage({ scriptFailure = false } = {}) {
  let footer = readFileSync(resolve(ROOT, 'layouts/partials/footer.html'), 'utf8')
    .replace('{{ now.Year }}', '2026');
  let consent = readFileSync(resolve(ROOT, 'layouts/partials/cookie-banner.html'), 'utf8')
    .replace(/\{\{\/\*[\s\S]*?\*\/\}\}/g, '')
    .replace(/^\{\{ \$ga_id[^\n]*\n/gm, '')
    .replace(/^\{\{ \$adConfig[^\n]*\n/gm, '')
    .replace('{{ $adConfig.consentRevision }}', '2')
    .replace("'{{ $ga_id }}'", `'${GA_ID}'`);

  assert.equal(consent.includes('{{'), false, 'test fixture must resolve Hugo expressions');
  if (scriptFailure) consent = consent.replace(/<script>[\s\S]*?<\/script>/, '');

  return `<!doctype html>
    <html lang="fi"><head><meta charset="utf-8"><title>Consent test</title></head>
    <body><main id="main-content"><h1>Luettava sisältö</h1></main>${footer}${consent}</body></html>`;
}

async function withServer(run) {
  const documentRequests = new Map();
  const server = createServer((request, response) => {
    const requestUrl = new URL(request.url ?? '/', 'http://127.0.0.1');
    const scriptFailure = requestUrl.pathname === '/script-failure/';
    documentRequests.set(requestUrl.pathname, (documentRequests.get(requestUrl.pathname) ?? 0) + 1);
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    response.end(renderConsentPage({ scriptFailure }));
  });
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));
  const address = server.address();
  assert(address && typeof address === 'object');
  try {
    await run(`http://127.0.0.1:${address.port}`, documentRequests);
  } finally {
    await new Promise((resolveClose, rejectClose) => {
      server.close((error) => error ? rejectClose(error) : resolveClose());
    });
  }
}

async function preparePage(browser) {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.setDefaultTimeout(5_000);
  const analyticsRequests = [];

  page.on('request', (request) => {
    const host = new URL(request.url()).hostname;
    if (ANALYTICS_HOSTS.has(host)) analyticsRequests.push(request.url());
  });
  await page.route('https://www.googletagmanager.com/**', async (route) => {
    await route.fulfill({
      contentType: 'application/javascript',
      body: `document.cookie='_ga=GA1.1.test; Path=/; SameSite=Lax';
        document.cookie='_ga_TEST123=session; Path=/; SameSite=Lax';
        fetch('https://region1.google-analytics.com/g/collect');`,
    });
  });
  await page.route('https://region1.google-analytics.com/**', (route) => route.fulfill({ status: 204, body: '' }));
  return { context, page, analyticsRequests };
}

test('OPE-453 consent remains fail-closed and revocation survives reload/navigation', async () => {
  await withServer(async (origin, documentRequests) => {
    const browser = await chromium.launch(browserLaunchOptions());
    try {
      {
        const { context, page, analyticsRequests } = await preparePage(browser);
        await page.goto(`${origin}/`);
        assert.equal(analyticsRequests.length, 0, 'first visit must emit zero analytics requests');
        await page.locator('#cb-reject').click();
        assert.equal(analyticsRequests.length, 0, 'reject must emit zero analytics requests');
        assert.equal(
          await page.evaluate(() => JSON.parse(localStorage.getItem('cookie_consent_v2')).analytics),
          false,
        );
        await page.reload();
        assert.equal(await page.locator('#cookie-banner').isHidden(), true);
        const settings = page.locator('#cookie-settings');
        await settings.focus();
        await page.keyboard.press('Enter');
        assert.equal(await page.locator('#cookie-modal').isVisible(), true, 'stored reject must retain settings handler');
        await page.keyboard.press('Escape');
        assert.equal(await settings.evaluate((element) => element === document.activeElement), true);
        analyticsRequests.length = 0;
        await page.goto(`${origin}/article/`);
        assert.equal(analyticsRequests.length, 0, 'reject navigation must remain zero analytics');
        assert.equal(await page.locator('#main-content').isVisible(), true);
        await context.close();
      }

      {
        const { context, page, analyticsRequests } = await preparePage(browser);
        await page.goto(`${origin}/`);
        await page.locator('#cb-customize').click();
        await page.locator('#cb-toggle-analytics').check();
        await page.locator('#cm-save').click();
        await page.waitForTimeout(50);
        assert(analyticsRequests.some((url) => url.includes('googletagmanager.com/gtag/js')));
        assert(analyticsRequests.some((url) => url.includes('google-analytics.com/g/collect')));
        assert.deepEqual(
          (await context.cookies()).map((cookie) => cookie.name).filter((name) => /^_ga(?:_|$)/.test(name)).sort(),
          ['_ga', '_ga_TEST123'],
        );

        await page.reload();
        await page.waitForTimeout(50);
        analyticsRequests.length = 0;
        const reloadCountBeforeRevocation = documentRequests.get('/') ?? 0;
        const settings = page.locator('#cookie-settings');
        await settings.focus();
        await page.keyboard.press('Enter');
        assert.equal(await page.locator('#cb-toggle-analytics').isChecked(), true);
        await page.locator('#cb-toggle-analytics').uncheck();
        await Promise.all([
          page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
          page.locator('#cm-save').click(),
        ]);

        assert((documentRequests.get('/') ?? 0) > reloadCountBeforeRevocation, 'withdrawal must reload deterministically');
        assert.equal(
          await page.evaluate(() => JSON.parse(localStorage.getItem('cookie_consent_v2')).analytics),
          false,
          'withdrawal must be persisted before reload',
        );
        assert.equal(await page.evaluate((id) => window[`ga-disable-${id}`], GA_ID), true, 'GA disable boundary must survive reload');
        assert.deepEqual(
          (await context.cookies()).map((cookie) => cookie.name).filter((name) => /^_ga(?:_|$)/.test(name)),
          [],
          'withdrawal must remove first-party GA cookies',
        );
        await page.waitForTimeout(50);
        assert.deepEqual(analyticsRequests, [], 'withdrawal reload must emit zero analytics requests');
        await page.goto(`${origin}/article/`);
        assert.deepEqual(analyticsRequests, [], 'post-withdrawal navigation must emit zero analytics requests');
        assert.equal(await page.locator('#main-content').isVisible(), true);
        await context.close();
      }

      {
        const { context, page, analyticsRequests } = await preparePage(browser);
        await page.goto(`${origin}/script-failure/`);
        assert.deepEqual(analyticsRequests, [], 'consent-script failure must emit zero analytics requests');
        assert.equal(await page.locator('#main-content').isVisible(), true, 'content must remain usable after consent-script failure');
        await context.close();
      }
    } finally {
      await browser.close();
    }
  });
});
