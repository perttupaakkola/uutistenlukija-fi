#!/usr/bin/env node

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const workerSource = await readFile(new URL('../static/_worker.js', import.meta.url), 'utf8');
const workerModuleUrl = `data:text/javascript;base64,${Buffer.from(workerSource).toString('base64')}`;
const worker = (await import(workerModuleUrl)).default;

function request(pathname, init) {
  return new Request(`https://uutistenlukija.fi${pathname}`, init);
}

function assetSpy() {
  const calls = [];
  return {
    calls,
    env: {
      ASSETS: {
        async fetch(assetRequest) {
          calls.push(assetRequest.url);
          return new Response('asset response', { status: 200 });
        },
      },
    },
  };
}

async function assertNoStore404(pathname) {
  const { calls, env } = assetSpy();
  const response = await worker.fetch(request(pathname), env, {});

  assert.equal(response.status, 404, pathname);
  assert.equal(response.headers.get('cache-control'), 'no-store', pathname);
  assert.equal(await response.text(), 'Not found', pathname);
  assert.deepEqual(calls, [], `${pathname} must not reach ASSETS.fetch`);
}

test('retired /tue path segment and descendants bypass ASSETS.fetch', async () => {
  for (const pathname of [
    '/tue',
    '/tue/',
    '/tue/index.xml',
    '/tue/archive/page',
    '/tue/index.xml?source=regression',
  ]) {
    await assertNoStore404(pathname);
  }
});

test('/tue lookalikes are normal assets', async () => {
  for (const pathname of ['/tuet', '/tuex', '/tuet/child', '/TUE', '/news/tue']) {
    const { calls, env } = assetSpy();
    const response = await worker.fetch(request(pathname), env, {});

    assert.equal(response.status, 200, pathname);
    assert.equal(await response.text(), 'asset response', pathname);
    assert.equal(calls.length, 1, `${pathname} must delegate once`);
    assert.equal(new URL(calls[0]).pathname, pathname);
  }
});

test('existing /tila retirement remains intercepted', async () => {
  for (const pathname of ['/tila', '/tila/', '/tila/status']) {
    await assertNoStore404(pathname);
  }
});

test('newsletter API and article redirects keep their existing routing', async () => {
  const apiSpy = assetSpy();
  const apiResponse = await worker.fetch(request('/api/subscribe'), apiSpy.env, {});
  assert.equal(apiResponse.status, 405);
  assert.equal((await apiResponse.json()).error, 'method_not_allowed');
  assert.deepEqual(apiSpy.calls, [], '/api/subscribe must not reach ASSETS.fetch');

  const redirectSpy = assetSpy();
  const redirectResponse = await worker.fetch(
    request('/posts/example-article/2?from=regression'),
    redirectSpy.env,
    {},
  );
  assert.equal(redirectResponse.status, 308);
  assert.equal(
    redirectResponse.headers.get('location'),
    'https://uutistenlukija.fi/posts/example-article/?from=regression',
  );
  assert.deepEqual(redirectSpy.calls, [], 'article redirect must not reach ASSETS.fetch');
});

test('fictional editorial surface redirects to the canonical disclosure', async () => {
  for (const pathname of ['/toimitus', '/toimitus/', '/toimitus/?legacy=1']) {
    const { calls, env } = assetSpy();
    const response = await worker.fetch(request(pathname), env, {});

    assert.equal(response.status, 308, pathname);
    assert.equal(
      response.headers.get('location'),
      'https://uutistenlukija.fi/tietoja/#toimitustapa',
      pathname,
    );
    assert.deepEqual(calls, [], `${pathname} must not reach ASSETS.fetch`);
  }
});

test('ordinary assets still delegate exactly once', async () => {
  const { calls, env } = assetSpy();
  const response = await worker.fetch(request('/css/style.css?rev=123'), env, {});

  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'asset response');
  assert.deepEqual(calls, ['https://uutistenlukija.fi/css/style.css?rev=123']);
});
