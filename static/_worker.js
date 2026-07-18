const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'content-type': 'application/json; charset=UTF-8',
      'cache-control': 'no-store',
    },
  });
}

function notFoundResponse() {
  return new Response('Not found', {
    status: 404,
    headers: {
      'content-type': 'text/plain; charset=UTF-8',
      'cache-control': 'no-store',
    },
  });
}

function blockedPublicStatusPath(pathname) {
  return (
    pathname === '/tila' ||
    pathname === '/tila/' ||
    pathname.startsWith('/tila/') ||
    pathname === '/tue' ||
    pathname === '/tue/' ||
    pathname.startsWith('/tue/')
  );
}

function readEnv(env, key) {
  const value = env?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

async function readPayload(request) {
  const contentType = request.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    return request.json();
  }

  if (
    contentType.includes('application/x-www-form-urlencoded') ||
    contentType.includes('multipart/form-data')
  ) {
    const form = await request.formData();
    return Object.fromEntries(form.entries());
  }

  return {};
}

async function resendRequest(env, path, init = {}) {
  const apiKey = readEnv(env, 'RESEND_API_KEY');
  const baseUrl = readEnv(env, 'RESEND_API_BASE_URL') || 'https://api.resend.com';

  return fetch(`${baseUrl}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
}

async function findExistingContact(env, email) {
  const audienceId = readEnv(env, 'RESEND_AUDIENCE_ID');
  const response = await resendRequest(env, `/audiences/${audienceId}/contacts`, {
    method: 'GET',
  });

  if (!response.ok) {
    if (response.status === 404) return null;
    const errorText = await response.text();
    throw new Error(`Resend contact lookup failed (${response.status}): ${errorText}`);
  }

  const data = await response.json();
  const contacts = data?.data || [];
  return contacts.find((c) => c.email?.toLowerCase() === email.toLowerCase()) || null;
}

async function createContact(env, email, source) {
  const audienceId = readEnv(env, 'RESEND_AUDIENCE_ID');

  const response = await resendRequest(env, `/audiences/${audienceId}/contacts`, {
    method: 'POST',
    body: JSON.stringify({
      email,
      unsubscribed: false,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Resend create contact failed (${response.status}): ${errorText}`);
  }

  return response.json();
}

async function sendWelcomeEmail(env, email) {
  const siteUrl = readEnv(env, 'SITE_URL') || 'https://uutistenlukija.fi';
  const homepageUrl = `${siteUrl.replace(/\/$/, '')}/`;
  const response = await resendRequest(env, '/emails', {
    method: 'POST',
    body: JSON.stringify({
      from: 'Uutistenlukija <info@uutistenlukija.fi>',
      to: [email],
      subject: 'Tervetuloa Uutistenlukijaan! 📰',
      html: `
        <div style="font-family:Inter,Arial,sans-serif;line-height:1.6;color:#1f2933;max-width:560px;margin:0 auto;padding:24px;">
          <h1 style="font-size:28px;line-height:1.2;margin:0 0 16px;color:#111827;">Tervetuloa Uutistenlukijaan</h1>
          <p style="margin:0 0 14px;">Kiitos tilauksesta. Saat meiltä tiiviit, selkeät ja olennaiset uutiset suomeksi ilman turhaa kiertelyä.</p>
          <p style="margin:0 0 14px;">Uutiskirjeessä nostamme esiin päivän tärkeimmät jutut, taustat ja linkit suoraan sivulle, jotta pääset nopeasti olennaiseen.</p>
          <p style="margin:0 0 20px;">Sillä välin voit lukea tuoreimmat uutiset tästä:</p>
          <p style="margin:0 0 24px;">
            <a href="${homepageUrl}" style="display:inline-block;background:#c0392b;color:#ffffff;text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:700;">Avaa Uutistenlukija</a>
          </p>
          <p style="margin:0;color:#6b7280;font-size:14px;">Tervetuloa mukaan.<br>Uutistenlukija</p>
        </div>
      `,
      text: [
        'Tervetuloa Uutistenlukijaan.',
        '',
        'Kiitos tilauksesta. Saat meiltä tiiviit, selkeät ja olennaiset uutiset suomeksi.',
        'Uutiskirjeessä nostamme esiin päivän tärkeimmät jutut, taustat ja linkit suoraan sivulle.',
        '',
        `Lue tuoreimmat uutiset: ${homepageUrl}`,
        '',
        'Tervetuloa mukaan,',
        'Uutistenlukija',
      ].join('\n'),
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Resend welcome email failed (${response.status}): ${errorText}`);
  }

  return response.json();
}

async function handleSubscribe(request, env) {
  if (request.method !== 'POST') {
    return jsonResponse({ ok: false, error: 'method_not_allowed' }, 405);
  }

  const apiKey = readEnv(env, 'RESEND_API_KEY');
  const audienceId = readEnv(env, 'RESEND_AUDIENCE_ID');
  if (!apiKey || !audienceId) {
    return jsonResponse({ ok: false, error: 'config_missing' }, 500);
  }

  let payload;
  try {
    payload = await readPayload(request);
  } catch {
    return jsonResponse({ ok: false, error: 'invalid_payload', message: 'Virheellinen pyyntö.' }, 400);
  }

  const email = String(payload?.email || '').trim().toLowerCase();
  const source = String(payload?.source || 'article').trim().slice(0, 80);

  if (!email || !EMAIL_RE.test(email) || email.length > 254) {
    return jsonResponse({ ok: false, error: 'invalid_email', message: 'Anna kelvollinen sähköpostiosoite.' }, 400);
  }

  try {
    const existingContact = await findExistingContact(env, email);
    if (existingContact?.id) {
      return jsonResponse(
        { ok: false, error: 'already_subscribed', message: 'Tämä sähköpostiosoite on jo uutiskirjeen tilaaja.' },
        409,
      );
    }

    await createContact(env, email, source);
    await sendWelcomeEmail(env, email);

    return jsonResponse({
      ok: true,
      message: 'Kiitos! Lähetämme pian ensimmäisen uutiskirjeemme.',
    });
  } catch (error) {
    console.error('newsletter subscribe failed', error);
    return jsonResponse(
      {
        ok: false,
        error: 'subscribe_failed',
        message: 'Tilauksen käsittely ei onnistunut juuri nyt. Yritä hetken päästä uudelleen.',
      },
      500,
    );
  }
}

function redirectedArticleSubpage(requestUrl) {
  const url = new URL(requestUrl);
  const match = url.pathname.match(/^(\/posts\/.+?)\/\d+\/?$/);
  if (!match) return null;

  url.pathname = `${match[1]}/`;
  return Response.redirect(url.toString(), 308);
}

function redirectedDuplicateKuubaOutage(requestUrl) {
  const url = new URL(requestUrl);
  const alternatePath =
    '/posts/2026-03-17-kuuban-sahkoverkko-romahti-kymmenen-miljoonaa-ihmista-jai-pi';
  const normalizedPath = url.pathname.endsWith('/')
    ? url.pathname.slice(0, -1)
    : url.pathname;
  if (normalizedPath !== alternatePath) return null;

  url.pathname =
    '/posts/2026-03-17-kuuban-sahkoverkko-romahti-ja-jatti-10-miljoonaa-ihmista-pim/';
  url.search = '';
  url.hash = '';
  return Response.redirect(url.toString(), 308);
}

function redirectedEditorialSurface(requestUrl) {
  const url = new URL(requestUrl);
  if (url.pathname !== '/toimitus' && url.pathname !== '/toimitus/') return null;

  url.pathname = '/tietoja/';
  url.search = '';
  url.hash = 'toimitustapa';
  return Response.redirect(url.toString(), 308);
}

function redirectedPrivacySurface(requestUrl) {
  const url = new URL(requestUrl);
  if (url.pathname !== '/tietosuoja' && url.pathname !== '/tietosuoja/') return null;

  url.pathname = '/tietosuojaseloste/';
  url.search = '';
  url.hash = '';
  return Response.redirect(url.toString(), 308);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (blockedPublicStatusPath(url.pathname)) {
      return notFoundResponse();
    }

    if (url.pathname === '/api/subscribe') {
      return handleSubscribe(request, env, ctx);
    }

    const privacySurfaceRedirect = redirectedPrivacySurface(request.url);
    if (privacySurfaceRedirect) {
      return privacySurfaceRedirect;
    }

    const editorialSurfaceRedirect = redirectedEditorialSurface(request.url);
    if (editorialSurfaceRedirect) {
      return editorialSurfaceRedirect;
    }

    const duplicateKuubaOutageRedirect = redirectedDuplicateKuubaOutage(request.url);
    if (duplicateKuubaOutageRedirect) {
      return duplicateKuubaOutageRedirect;
    }

    const articleSubpageRedirect = redirectedArticleSubpage(request.url);
    if (articleSubpageRedirect) {
      return articleSubpageRedirect;
    }

    return env.ASSETS.fetch(request);
  },
};
