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

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/api/subscribe') {
      return handleSubscribe(request, env, ctx);
    }

    return env.ASSETS.fetch(request);
  },
};
