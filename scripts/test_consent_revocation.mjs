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

function relativeLuminance(rgb) {
  const linear = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrastRatio(foreground, background) {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
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

  const criticalCss = readFileSync(resolve(ROOT, 'layouts/partials/critical-css.html'), 'utf8');
  const fullCss = readFileSync(resolve(ROOT, 'themes/uutistenlukija/static/css/style.css'), 'utf8');
  const portalCss = readFileSync(resolve(ROOT, 'static/css/portal-overhaul.css'), 'utf8');

  return `<!doctype html>
    <html lang="fi"><head><meta charset="utf-8"><title>Consent test</title>
    ${criticalCss}<style>${fullCss}\n${portalCss}</style></head>
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

test('OPE-452 consent status label keeps rendered AA contrast in both themes', async () => {
  await withServer(async (origin) => {
    const browser = await chromium.launch(browserLaunchOptions());
    try {
      for (const viewport of [{ width: 390, height: 844 }, { width: 1366, height: 900 }]) {
        for (const theme of ['light', 'dark']) {
          const context = await browser.newContext({ viewport });
          const page = await context.newPage();
          await page.goto(`${origin}/`);
          await page.evaluate((selectedTheme) => {
            document.documentElement.setAttribute('data-theme', selectedTheme);
          }, theme);
          await page.locator('#cb-customize').click();

          const colors = await page.locator('.cm-always-on').evaluate((label) => {
            const parseRgb = (value) => {
              const match = value.match(/rgba?\(([^)]+)\)/);
              if (!match) throw new Error(`Unsupported rendered color: ${value}`);
              return match[1].split(',').slice(0, 3).map((part) => Number.parseFloat(part.trim()));
            };
            let surface = label;
            while (surface && getComputedStyle(surface).backgroundColor === 'rgba(0, 0, 0, 0)') {
              surface = surface.parentElement;
            }
            if (!surface) throw new Error('status label must render on an opaque ancestor');
            return {
              foreground: parseRgb(getComputedStyle(label).color),
              background: parseRgb(getComputedStyle(surface).backgroundColor),
            };
          });

          assert(
            contrastRatio(colors.foreground, colors.background) >= 4.5,
            `${viewport.width}px ${theme} status-label contrast must be at least 4.5:1`,
          );
          await context.close();
        }
      }
    } finally {
      await browser.close();
    }
  });
});

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
        await page.locator('label[aria-label="Analytiikkaevästeet"]').click();
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
        await page.locator('label[aria-label="Analytiikkaevästeet"]').click();
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
