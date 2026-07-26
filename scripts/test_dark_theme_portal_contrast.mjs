#!/usr/bin/env node
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { chromium } from 'playwright';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 1366, height: 900 },
];
const ARTICLE_BADGE_CASES = [
  {
    key: 'talous',
    slug: 'talous',
    label: 'Talous',
    background: '#f39c12',
    backgroundRgb: [243, 156, 18],
    foregroundByTheme: {
      light: [7, 19, 41],
      dark: [7, 19, 41],
    },
  },
  {
    key: 'teknologia',
    slug: 'teknologia',
    label: 'Teknologia',
    background: '#8e44ad',
    backgroundRgb: [142, 68, 173],
    foregroundByTheme: {
      light: [255, 255, 255],
      dark: [243, 245, 247],
    },
  },
  {
    key: 'default',
    slug: 'default',
    label: 'Muu',
    background: '#c0392b',
    backgroundRgb: [192, 57, 43],
    foregroundByTheme: {
      light: [255, 255, 255],
      dark: [243, 245, 247],
    },
  },
];
const CONTRAST_TARGETS = [
  ['.portal-livebar__all', 'live-update CTA'],
  ['[data-market-list] dd', 'market value'],
  ['.bc-current', 'current breadcrumb'],
  ['.portal-list-feature__body > p', 'list feature excerpt'],
  ['.portal-feed-item p', 'feed excerpt'],
  ['.single-article > .category-label--badge', 'article category badge'],
];

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

function breadcrumbCss() {
  const partial = readFileSync(resolve(ROOT, 'layouts/partials/breadcrumbs.html'), 'utf8');
  const style = partial.match(/<style>([\s\S]*?)<\/style>/);
  assert(style, 'breadcrumb partial must retain its scoped style block');
  return style[1];
}

function renderFixture(theme = 'dark', articleBadges = [ARTICLE_BADGE_CASES[1]]) {
  const criticalCss = readFileSync(resolve(ROOT, 'layouts/partials/critical-css.html'), 'utf8');
  const fullCss = readFileSync(resolve(ROOT, 'themes/uutistenlukija/static/css/style.css'), 'utf8');
  const portalCss = readFileSync(resolve(ROOT, 'static/css/portal-overhaul.css'), 'utf8');
  const badgeMarkup = articleBadges.map((badge) => `
        <article class="single-article">
          <a data-contrast-case="${badge.key}"
             class="category-label category-label--badge category-label--${badge.slug}"
             href="#category-${badge.key}"
             style="background-color:${badge.background};border-color:${badge.background}">
            ${badge.label}
          </a>
        </article>`).join('');

  return `<!doctype html>
    <html lang="fi" data-theme="${theme}"><head><meta charset="utf-8"><title>Portal contrast</title>
    ${criticalCss}<style>${fullCss}</style><style>${portalCss}</style><style>${breadcrumbCss()}</style>
    </head><body>
      <a class="skip-to-content" href="#main-content">Siirry pääsisältöön</a>
      <header class="site-header">
        <nav class="main-nav" id="main-nav-menu" aria-label="Päävalikko">
          <ul><li><a id="test-main-nav-link" href="#home">Etusivu</a></li></ul>
        </nav>
      </header>
      <main id="main-content" class="container">
        <a class="portal-livebar" href="#updates">
          <span class="portal-livebar__all">Katso kaikki päivitykset</span>
        </a>
        <section class="portal-market" data-market-list>
          <dl><div><dt>Bitcoin</dt><dd>57 849 €</dd></div></dl>
        </section>
        <nav class="breadcrumbs" aria-label="Murupolku">
          <span class="bc-current" aria-current="page">Talous</span>
        </nav>
        <section class="portal-list-feature">
          <div class="portal-list-feature__body"><p>Nostoartikkelin ingressi.</p></div>
        </section>
        <article class="portal-feed-item"><div><p>Uutisvirran ingressi.</p></div></article>
        ${badgeMarkup}
      </main>
    </body></html>`;
}

async function withServer(run, theme = 'dark', articleBadges) {
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    response.end(renderFixture(theme, articleBadges));
  });
  await new Promise((resolveListen) => server.listen(0, '127.0.0.1', resolveListen));
  const address = server.address();
  assert(address && typeof address === 'object');
  try {
    await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolveClose, rejectClose) => {
      server.close((error) => error ? rejectClose(error) : resolveClose());
    });
  }
}

test('OPE-363 scopes portal navy to Talous and preserves other article badges', async () => {
  for (const theme of ['light', 'dark']) {
    await withServer(async (origin) => {
      const browser = await chromium.launch(browserLaunchOptions());
      try {
        for (const viewport of VIEWPORTS) {
          const context = await browser.newContext({ viewport });
          const page = await context.newPage();
          await page.goto(origin);
          assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
          for (const badge of ARTICLE_BADGE_CASES) {
            const locator = page.locator(`[data-contrast-case="${badge.key}"]`);
            assert.equal(await locator.count(), 1, `${badge.key} fixture must resolve once`);
            const colors = await locator.evaluate((element) => {
              const parseRgb = (value) => value
                .match(/rgba?\(([^)]+)\)/)[1]
                .replace('/', ' ')
                .split(/[\s,]+/)
                .filter(Boolean)
                .slice(0, 3)
                .map((part) => Number.parseFloat(part));
              const style = getComputedStyle(element);
              return {
                foreground: parseRgb(style.color),
                background: parseRgb(style.backgroundColor),
              };
            });
            assert.deepEqual(
              colors.foreground,
              badge.foregroundByTheme[theme],
              `${viewport.width}px ${theme} ${badge.key} badge must preserve its foreground`,
            );
            assert.deepEqual(
              colors.background,
              badge.backgroundRgb,
              `${viewport.width}px ${theme} ${badge.key} badge must preserve its background`,
            );
            const ratio = contrastRatio(colors.foreground, colors.background);
            assert(
              ratio >= 4.5,
              `${viewport.width}px ${theme} ${badge.key} badge contrast ${ratio.toFixed(4)} must be at least 4.5:1`,
            );
          }
          await context.close();
        }
      } finally {
        await browser.close();
      }
    }, theme, ARTICLE_BADGE_CASES);
  }
});

test('OPE-446 dark portal text reaches rendered WCAG AA contrast', async () => {
  await withServer(async (origin) => {
    const browser = await chromium.launch(browserLaunchOptions());
    try {
      for (const viewport of VIEWPORTS) {
        const context = await browser.newContext({ viewport });
        const page = await context.newPage();
        await page.goto(origin);
        assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');

        for (const [selector, label] of CONTRAST_TARGETS) {
          const locator = page.locator(selector);
          assert.equal(await locator.count(), 1, `${label} fixture must resolve once`);
          const colors = await locator.evaluate((element) => {
            const parseRgb = (value) => {
              const match = value.match(/rgba?\(([^)]+)\)/);
              if (!match) throw new Error(`Unsupported rendered color: ${value}`);
              return match[1]
                .replace('/', ' ')
                .split(/[\s,]+/)
                .filter(Boolean)
                .slice(0, 3)
                .map((part) => Number.parseFloat(part));
            };
            let surface = element;
            while (surface && getComputedStyle(surface).backgroundColor === 'rgba(0, 0, 0, 0)') {
              surface = surface.parentElement;
            }
            if (!surface) throw new Error('contrast target must render on an opaque ancestor');
            return {
              foreground: parseRgb(getComputedStyle(element).color),
              background: parseRgb(getComputedStyle(surface).backgroundColor),
            };
          });
          const ratio = contrastRatio(colors.foreground, colors.background);
          assert(
            ratio >= 4.5,
            `${viewport.width}px dark ${label} contrast ${ratio.toFixed(4)} must be at least 4.5:1`,
          );
        }
        await context.close();
      }
    } finally {
      await browser.close();
    }
  });
});

test('OPE-446 keeps the accepted dark skip-link keyboard focus contrast', async () => {
  await withServer(async (origin) => {
    const browser = await chromium.launch(browserLaunchOptions());
    try {
      for (const viewport of VIEWPORTS) {
        const context = await browser.newContext({ viewport });
        const page = await context.newPage();
        await page.goto(origin);
        await page.keyboard.press('Tab');
        assert.equal(
          await page.evaluate(() => document.activeElement?.classList.contains('skip-to-content')),
          true,
          `${viewport.width}px first Tab must expose the skip link`,
        );
        const focus = await page.locator('.skip-to-content').evaluate((element) => {
          const parseRgb = (value) => value
            .match(/rgba?\(([^)]+)\)/)[1]
            .replace('/', ' ')
            .split(/[\s,]+/)
            .filter(Boolean)
            .slice(0, 3)
            .map((part) => Number.parseFloat(part));
          const style = getComputedStyle(element);
          return {
            text: parseRgb(style.color),
            panel: parseRgb(style.backgroundColor),
            outline: parseRgb(style.outlineColor),
            outlineWidth: Number.parseFloat(style.outlineWidth),
            page: parseRgb(getComputedStyle(document.body).backgroundColor),
          };
        });
        assert(contrastRatio(focus.text, focus.panel) >= 4.5);
        assert(focus.outlineWidth >= 3, 'skip-link outline must remain at least 3px');
        assert(contrastRatio(focus.outline, focus.panel) >= 3);
        assert(contrastRatio(focus.outline, focus.page) >= 3);
        await context.close();
      }
    } finally {
      await browser.close();
    }
  });
});

test('OPE-446 dark desktop main-nav focus outline reaches 3:1', async () => {
  const compact = (value) => value
    .replace(/\s+/g, '')
    .replaceAll('"', '')
    .replaceAll(';}', '}');
  const expectedLock = compact('@media (min-width: 681px) { :root[data-theme="dark"] #main-nav-menu a:focus-visible { outline-color: var(--accent, #e74c3c); } }');
  const portalAssetCss = readFileSync(resolve(ROOT, 'assets/css/portal-overhaul.css'), 'utf8');
  const portalStaticCss = readFileSync(resolve(ROOT, 'static/css/portal-overhaul.css'), 'utf8');
  assert.equal(portalAssetCss, portalStaticCss, 'portal CSS mirrors must remain byte-identical');
  for (const [label, source] of [
    ['portal CSS', portalAssetCss],
    ['critical CSS', readFileSync(resolve(ROOT, 'layouts/partials/critical-css.html'), 'utf8')],
    ['critical CSS generator', readFileSync(resolve(ROOT, 'pipeline/extract_critical_css.py'), 'utf8')],
  ]) {
    assert(
      compact(source).includes(expectedLock),
      `${label} must retain the dark desktop main-nav focus lock`,
    );
  }
  await withServer(async (origin) => {
    const browser = await chromium.launch(browserLaunchOptions());
    try {
      const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
      const page = await context.newPage();
      await page.goto(origin);
      await page.keyboard.press('Tab');
      await page.keyboard.press('Tab');
      assert.equal(
        await page.evaluate(() => document.activeElement?.id),
        'test-main-nav-link',
        'second desktop Tab must focus the first main-nav link',
      );
      const focus = await page.locator('#test-main-nav-link').evaluate((element) => {
        const parseRgb = (value) => value
          .match(/rgba?\(([^)]+)\)/)[1]
          .replace('/', ' ')
          .split(/[\s,]+/)
          .filter(Boolean)
          .slice(0, 3)
          .map((part) => Number.parseFloat(part));
        const style = getComputedStyle(element);
        const nav = element.closest('#main-nav-menu');
        return {
          outline: parseRgb(style.outlineColor),
          outlineWidth: Number.parseFloat(style.outlineWidth),
          outlineOffset: Number.parseFloat(style.outlineOffset),
          background: parseRgb(getComputedStyle(nav).backgroundColor),
        };
      });
      assert.equal(focus.outlineWidth, 3, 'main-nav outline geometry must stay 3px');
      assert.equal(focus.outlineOffset, 2, 'main-nav outline offset must stay 2px');
      assert.deepEqual(focus.outline, [231, 76, 60], 'dark accent token must drive the outline');
      assert.deepEqual(focus.background, [36, 33, 29], 'fixture must retain the accepted dark nav surface');
      assert(
        contrastRatio(focus.outline, focus.background) >= 3,
        `dark desktop main-nav focus contrast ${contrastRatio(focus.outline, focus.background).toFixed(4)} must be at least 3:1`,
      );
      await context.close();
    } finally {
      await browser.close();
    }
  });
});
