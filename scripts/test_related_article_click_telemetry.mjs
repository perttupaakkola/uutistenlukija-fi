#!/usr/bin/env node

import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';

const publicDir = process.argv[2];
assert.ok(publicDir, 'usage: test_related_article_click_telemetry.mjs PUBLIC_DIR');

const sourceSlugs = [
  '2026-07-12-argentiina-eteni-valieriin-dramaattisten-vaiheiden-jalkeen-e',
  '2026-07-12-haaland-uupui-mm-puolivalierassa-norjassa-raivostuttiin-tuom',
];
const targetPath = '/posts/2026-04-30-mm-kisoissa-voidaan-antaa-punainen-kortti-myos-suun-peittami/';

const browser = await chromium.launch({ headless: true });
try {
  for (const slug of sourceSlugs) {
    const url = pathToFileURL(path.join(publicDir, 'posts', slug, 'index.html')).href;

    for (const selector of [
      `.related-card:has(a[href="${targetPath}"]) > a.article-image-link`,
      `.related-card:has(a[href="${targetPath}"]) .related-card__title > a`,
    ]) {
      const page = await browser.newPage();
      await page.addInitScript(() => {
        window.__gtagCalls = [];
        window.gtag = (...args) => window.__gtagCalls.push(args);
        document.addEventListener('click', (event) => event.preventDefault(), true);
      });
      await page.goto(url);
      const anchor = page.locator(selector);
      await assert.doesNotReject(() => anchor.waitFor({ state: 'attached' }));
      assert.equal(await anchor.getAttribute('data-track'), 'related_article_click');
      assert.equal(await anchor.getAttribute('onclick'), null);
      await anchor.click();
      const calls = await page.evaluate(() => window.__gtagCalls);
      const relatedCalls = calls.filter((call) => call[0] === 'event' && call[1] === 'related_article_click');
      assert.equal(relatedCalls.length, 1, `${slug} ${selector}: expected one related click event`);
      assert.equal(new URL(relatedCalls[0][2].link_url).pathname, targetPath);
      assert.equal(Object.keys(relatedCalls[0][2]).some((key) => /email|name|user|title/i.test(key)), false);
      await page.close();
    }

    const rejected = await browser.newPage();
    await rejected.addInitScript(() => {
      document.addEventListener('click', (event) => event.preventDefault(), true);
    });
    await rejected.goto(url);
    assert.equal(await rejected.evaluate(() => typeof window.gtag), 'undefined');
    await rejected.locator(`.related-card:has(a[href="${targetPath}"]) .related-card__title > a`).click();
    assert.equal(await rejected.evaluate(() => typeof window.gtag), 'undefined');
    assert.equal(await rejected.evaluate(() => typeof window.dataLayer), 'undefined');
    await rejected.close();
  }
} finally {
  await browser.close();
}

console.log('related article click telemetry: 2 pages x image/title emit once; rejected consent emits none — PASS');
