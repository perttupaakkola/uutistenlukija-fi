#!/usr/bin/env node

import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import test from 'node:test';

const workerSource = await readFile(new URL('../static/_worker.js', import.meta.url), 'utf8');
const workerModuleUrl = `data:text/javascript;base64,${Buffer.from(workerSource).toString('base64')}`;
const worker = (await import(workerModuleUrl)).default;
const rankedKuubaSlug =
  '2026-03-17-kuuban-sahkoverkko-romahti-ja-jatti-10-miljoonaa-ihmista-pim';
const alternateKuubaSlug =
  '2026-03-17-kuuban-sahkoverkko-romahti-kymmenen-miljoonaa-ihmista-jai-pi';
const jyvaskylaSurvivorSlug =
  '2026-03-20-jyvaskylassa-lahihoitajalle-tuomio-tietosuojarikoksista';
const retiredJyvaskylaBodyHashes = new Map([
  [
    '2026-03-20-lahihoitajalle-tuomio-186-tietosuojarikoksesta-jyvaskylassa',
    '6d666607c20ebe0e84bc4febd4ddd8dff4699a2a24925ee2f55848419109ca24',
  ],
  [
    '2026-03-20-lahihoitajalle-tuomio-186-tietosuojarikoksesta-katseli-luvat',
    '5ad901cbb92cc6460d354fa04c8e8595761cec19ba907c70227f89899dd65d75',
  ],
  [
    '2026-03-20-lahihoitajalle-tuomio-186-tietosuojarikoksesta-luvaton-paasy',
    'a8e7e832dcb919b8ca4a939c6db891564652dc96ec9a52b77c9045f8a852b589',
  ],
  [
    '2026-03-20-jyvaskylan-lahihoitaja-sai-tuomion-massiivisista-tietosuojar',
    'd23719da24e53bd85298c99fb5bd34ed7731d381f80c5cd9fd1222fc0ff9c2fa',
  ],
]);

function articleBody(source) {
  const marker = '\n---\n';
  const bodyStart = source.indexOf(marker);
  assert.notEqual(bodyStart, -1, 'article must have a closing frontmatter delimiter');
  return source.slice(bodyStart + marker.length);
}

function bodyHash(source) {
  return createHash('sha256').update(articleBody(source)).digest('hex');
}

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

test('duplicate Kuuba outage URL redirects one hop to the ranked canonical', async () => {
  const canonicalUrl = `https://uutistenlukija.fi/posts/${rankedKuubaSlug}/`;
  for (const pathname of [
    `/posts/${alternateKuubaSlug}`,
    `/posts/${alternateKuubaSlug}/`,
    `/posts/${alternateKuubaSlug}/?source=regression`,
  ]) {
    const { calls, env } = assetSpy();
    const response = await worker.fetch(request(pathname), env, {});

    assert.equal(response.status, 308, pathname);
    assert.equal(response.headers.get('location'), canonicalUrl, pathname);
    assert.deepEqual(calls, [], `${pathname} must not reach ASSETS.fetch`);
  }

  const canonicalSpy = assetSpy();
  const canonicalResponse = await worker.fetch(
    request(`/posts/${rankedKuubaSlug}/`),
    canonicalSpy.env,
    {},
  );
  assert.equal(canonicalResponse.status, 200);
  assert.deepEqual(canonicalSpy.calls, [canonicalUrl]);
});

test('duplicate Kuuba source is retired from index and first-party content links', async () => {
  const alternateSource = await readFile(
    new URL(`../content/posts/${alternateKuubaSlug}.md`, import.meta.url),
    'utf8',
  );
  assert.match(alternateSource, /^draft:\s*true$/m);

  const contentRoot = new URL('../content/', import.meta.url);
  const contentPaths = await readdir(contentRoot, { recursive: true });
  const offenders = [];
  for (const relativePath of contentPaths.filter((path) => path.endsWith('.md'))) {
    if (relativePath === `posts/${alternateKuubaSlug}.md`) continue;
    const source = await readFile(new URL(relativePath, contentRoot), 'utf8');
    if (source.includes(alternateKuubaSlug)) offenders.push(relativePath);
  }
  assert.deepEqual(offenders, [], 'published content must link directly to the ranked URL');

  const searchIndex = JSON.parse(
    await readFile(new URL('../static/search-index.json', import.meta.url), 'utf8'),
  );
  const urls = searchIndex.map((record) => record.url);
  assert.equal(urls.filter((url) => url === `/posts/${alternateKuubaSlug}/`).length, 0);
  assert.equal(urls.filter((url) => url === `/posts/${rankedKuubaSlug}/`).length, 1);
});

test('Jyväskylä privacy duplicates redirect exactly one hop to the source-safe survivor', async () => {
  const canonicalUrl = `https://uutistenlukija.fi/posts/${jyvaskylaSurvivorSlug}/`;
  for (const slug of retiredJyvaskylaBodyHashes.keys()) {
    for (const pathname of [
      `/posts/${slug}`,
      `/posts/${slug}/`,
      `/posts/${slug}/?source=regression`,
    ]) {
      const { calls, env } = assetSpy();
      const response = await worker.fetch(request(pathname), env, {});

      assert.equal(response.status, 308, pathname);
      assert.equal(response.headers.get('location'), canonicalUrl, pathname);
      assert.deepEqual(calls, [], `${pathname} must not reach ASSETS.fetch before redirect`);

      const followed = await worker.fetch(new Request(response.headers.get('location')), env, {});
      assert.equal(followed.status, 200, `${pathname} must finish after one redirect`);
      assert.deepEqual(calls, [canonicalUrl], `${pathname} must reach the survivor once`);
    }
  }

  const survivorSpy = assetSpy();
  const survivorResponse = await worker.fetch(
    request(`/posts/${jyvaskylaSurvivorSlug}/`),
    survivorSpy.env,
    {},
  );
  assert.equal(survivorResponse.status, 200);
  assert.deepEqual(survivorSpy.calls, [canonicalUrl]);
});

test('Jyväskylä survivor matches the accepted source-bounded contract', async () => {
  const survivor = await readFile(
    new URL(`../content/posts/${jyvaskylaSurvivorSlug}.md`, import.meta.url),
    'utf8',
  );
  assert.match(
    survivor,
    /^title: "Jyväskylässä lähihoitajalle tuomio tietosuojarikoksista"$/m,
  );
  assert.match(
    survivor,
    /^description: "Keski-Suomen käräjäoikeus tuomitsi lähihoitajan neljän kuukauden ehdolliseen vankeuteen 186 ihmisen potilastietojen luvattomasta katselusta\."$/m,
  );
  assert.match(survivor, /^source_name: "Yle"$/m);
  assert.match(survivor, /^source_url: "https:\/\/yle\.fi\/a\/74-20216112"$/m);
  assert.match(survivor, /^source_domain: "yle\.fi"$/m);
  assert.match(survivor, /^editorial_reviewed: true$/m);
  assert.ok(
    survivor.includes(
      '  Artikkeli perustuu Ylen 20.3.2026 julkaisemaan selostukseen Keski-Suomen käräjäoikeuden kansliatuomiosta. Ylen mukaan tuomio ei ollut julkaisuhetkellä lainvoimainen.',
    ),
  );
  assert.doesNotMatch(survivor, /^\s+- liikenne$/m);
  assert.equal(
    articleBody(survivor).trim(),
    `Keski-Suomen käräjäoikeus tuomitsi lähihoitajan neljän kuukauden ehdolliseen vankeuteen laajassa tietosuojarikosjutussa. Ylen 20. maaliskuuta julkaiseman uutisen mukaan lähihoitajan todettiin katselleen luvatta 186 ihmisen potilastietoja Keski-Suomen hyvinvointialueella. Vastaajaa syytettiin alun perin 192 tietosuojarikoksesta, joista kuusi hylättiin. Tuomio ei ollut Ylen uutisen julkaisuhetkellä lainvoimainen.

## Tietoja katsottiin huhtikuusta 2022 kesäkuuhun 2023

Luvattomat haut tehtiin huhtikuun 2022 ja kesäkuun 2023 välisenä aikana. Monien asianomistajien tietoja oli katsottu useita kertoja, enimmillään lähes 30 kertaa. Työnantajaa edustaneiden todistajien mukaan lähihoitaja oli kuulemistilaisuuksissa kertonut motiivikseen uteliaisuuden ja mielenkiinnon. Monet ihmiset, joiden tietoja katsottiin, olivat hänelle puolituttuja.

Lähihoitaja kiisti syytteet ja vaati niiden hylkäämistä puutteelliseen perehdytykseen vedoten. Käräjäoikeuden mukaan perehdytys oli asianmukainen. Myös todistajat kertoivat, että potilastietojen käyttöä koskevat ohjeet oli annettu sekä työsuhteen aikana että jo opintojen alussa.

## Korvauksia ja kuluja yli 37 000 euroa

Ylen mukaan lähihoitaja määrättiin maksamaan korvauksia ja oikeudenkäyntikuluja yhteensä yli 37 000 euroa. Uhreille maksettavien korvausten osuus oli lähes 19 000 euroa, ja kärsimyskorvaukset vaihtelivat 350 eurosta 600 euroon. Käräjäoikeus ei sovitellut korvauksia.

**Korjaus 18.7.2026:** Artikkeliin lisättiin lähdeviittaus. Samalla syytteiden määrä, korvaukset, motiivin lähde ja tuomion lainvoimaisuutta koskeva tieto täsmennettiin. Neljä samasta tapauksesta kertonutta päällekkäistä artikkelia yhdistettiin tähän sivuun.`,
  );
});

test('Jyväskylä retirees keep their bodies and leave discovery and first-party links', async () => {
  for (const [slug, expectedHash] of retiredJyvaskylaBodyHashes) {
    const source = await readFile(new URL(`../content/posts/${slug}.md`, import.meta.url), 'utf8');
    assert.match(source, /^draft:\s*true$/m, slug);
    assert.equal(bodyHash(source), expectedHash, `${slug} body must remain byte-identical`);
  }

  const contentRoot = new URL('../content/', import.meta.url);
  const contentPaths = await readdir(contentRoot, { recursive: true });
  const offenders = [];
  for (const relativePath of contentPaths.filter((path) => path.endsWith('.md'))) {
    const source = await readFile(new URL(relativePath, contentRoot), 'utf8');
    for (const slug of retiredJyvaskylaBodyHashes.keys()) {
      if (source.includes(slug)) offenders.push(`${relativePath}: ${slug}`);
    }
  }
  assert.deepEqual(offenders, [], 'first-party content must link directly to the survivor');

  const searchIndex = JSON.parse(
    await readFile(new URL('../static/search-index.json', import.meta.url), 'utf8'),
  );
  const urls = searchIndex.map((record) => record.url);
  for (const slug of retiredJyvaskylaBodyHashes.keys()) {
    assert.equal(urls.filter((url) => url === `/posts/${slug}/`).length, 0, slug);
  }
  assert.equal(urls.filter((url) => url === `/posts/${jyvaskylaSurvivorSlug}/`).length, 1);
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

test('retired privacy surface redirects permanently to the canonical statement', async () => {
  for (const pathname of ['/tietosuoja', '/tietosuoja/', '/tietosuoja/?legacy=1']) {
    const { calls, env } = assetSpy();
    const response = await worker.fetch(request(pathname), env, {});

    assert.equal(response.status, 308, pathname);
    assert.equal(
      response.headers.get('location'),
      'https://uutistenlukija.fi/tietosuojaseloste/',
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
