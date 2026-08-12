#!/usr/bin/env node

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const {
  ARTICLE_SEARCH_ALIASES_BY_URL,
  prepareItem,
  rankResults,
} = require('../static/js/search.js');

const TARGET = '/posts/2026-06-25-raystaspaaskyjen-pesinta-viivastyttaa-hailuodon-lauttojen-si/';
const APPROVED_DESCRIPTION = 'Hailuodon lauttojen siirto viivästyy, sillä lautoilla pesivillä uhanalaisilla räystäspääskyillä on yli sata poikasta.';
const records = JSON.parse(readFileSync(resolve(ROOT, 'static/search-index.json'), 'utf8'));
const noAliases = Object.create(null);
const baselineItems = records.map((record) => prepareItem(record, noAliases));
const candidateItems = records.map((record) => prepareItem(record));

test('OPE-507 scopes the Hailuoto alias to exactly one target result', () => {
  assert.deepEqual(ARTICLE_SEARCH_ALIASES_BY_URL, { [TARGET]: ['Hailuoto'] });
  assert.deepEqual(rankResults(baselineItems, 'Hailuoto'), []);

  const results = rankResults(candidateItems, 'Hailuoto');
  assert.deepEqual(results.map((item) => item.slug), [TARGET]);
  assert.equal(results[0].summary, APPROVED_DESCRIPTION);
});

test('OPE-507 preserves Hailuodon behavior and every non-target haystack', () => {
  const baselineUrls = rankResults(baselineItems, 'Hailuodon').map((item) => item.slug);
  const candidateUrls = rankResults(candidateItems, 'Hailuodon').map((item) => item.slug);
  assert.deepEqual(candidateUrls, baselineUrls);
  assert.equal(candidateUrls.filter((url) => url === TARGET).length, 1);
  assert(candidateUrls.length >= 2);

  for (let index = 0; index < candidateItems.length; index += 1) {
    if (candidateItems[index].slug === TARGET) continue;
    assert.equal(candidateItems[index].haystack, baselineItems[index].haystack);
  }
});
