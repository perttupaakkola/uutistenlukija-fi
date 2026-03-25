"""
Newsletter email capture API — lightweight FastAPI service.

Accepts POST /subscribe with email field, stores to SQLite,
deduplicates, returns JSON or redirects to thank-you page.

Usage:
    pip install fastapi uvicorn
    uvicorn newsletter_api:app --host 0.0.0.0 --port 8765

Env:
    NEWSLETTER_DB   path to SQLite file (default: pipeline/data/newsletter.db)
    NEWSLETTER_CORS comma-separated allowed origins (default: https://uutistenlukija.fi)
    NEWSLETTER_KEY  optional API key for /admin/subscribers export

Systemd service: see scripts/newsletter-api.service
"""
import os
import sqlite3
import re
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    from fastapi import FastAPI, Form, Request, HTTPException, Depends
    from fastapi.responses import JSONResponse, RedirectResponse
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    if __name__ == "__main__":
        raise SystemExit("fastapi not installed — run: pip install fastapi uvicorn")
    # Allow module to be imported for inspection (e.g. smoke_test.py)
    # without killing the importing process. Actual usage will fail
    # at the FastAPI() call below, which is fine.
    raise

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH = Path(os.environ.get(
    "NEWSLETTER_DB",
    Path(__file__).parent / "data" / "newsletter.db"
))
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("NEWSLETTER_CORS", "https://uutistenlukija.fi").split(",")
    if o.strip()
]
API_KEY = os.environ.get("NEWSLETTER_KEY", "")
THANK_YOU_URL = "/uutiskirje/"

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                subscribed_at TEXT  NOT NULL,
                source      TEXT    DEFAULT 'article',
                ip_hash     TEXT,
                confirmed   INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribe_attempts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_hash     TEXT,
                attempted_at TEXT NOT NULL
            )
        """)
        conn.commit()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Rate limiting (per IP, 5 attempts per hour) ───────────────────────────────

def check_rate_limit(ip_hash: str) -> bool:
    """Return True if allowed, False if rate-limited."""
    cutoff = datetime.fromtimestamp(time.time() - 3600, tz=timezone.utc).isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM subscribe_attempts WHERE ip_hash=? AND attempted_at>?",
            (ip_hash, cutoff)
        ).fetchone()
        count = row[0]
        if count >= 5:
            return False
        conn.execute(
            "INSERT INTO subscribe_attempts (ip_hash, attempted_at) VALUES (?, ?)",
            (ip_hash, datetime.now(timezone.utc).isoformat())
        )
    return True


def _ip_hash(request: Request) -> str:
    """Hash the client IP for privacy-safe rate limiting."""
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    ip = ip.split(",")[0].strip()
    return secrets.token_hex(4) if ip == "unknown" else str(hash(ip) & 0xFFFFFFFF)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Uutistenlukija Newsletter API", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.on_event("startup")
async def startup():
    init_db()


@app.post("/subscribe")
async def subscribe(
    request: Request,
    email: str = Form(...),
    source: str = Form(default="article"),
    redirect: str = Form(default="1"),
):
    """Subscribe an email address.

    Returns:
        - redirect=1 (default): HTTP 302 to thank-you page
        - redirect=0: JSON response (for AJAX)
    """
    # Validate
    email = email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 254:
        if redirect == "0":
            return JSONResponse({"ok": False, "error": "invalid_email"}, status_code=400)
        return RedirectResponse(f"{THANK_YOU_URL}?status=invalid", status_code=302)

    # Rate limit
    ip_hash = _ip_hash(request)
    if not check_rate_limit(ip_hash):
        if redirect == "0":
            return JSONResponse({"ok": False, "error": "rate_limited"}, status_code=429)
        return RedirectResponse(f"{THANK_YOU_URL}?status=error", status_code=302)

    # Insert (ignore duplicates)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM subscribers WHERE email=?", (email,)
        ).fetchone()

        if existing:
            # Already subscribed — treat as success (don't leak existence)
            if redirect == "0":
                return JSONResponse({"ok": True, "status": "already_subscribed"})
            return RedirectResponse(f"{THANK_YOU_URL}?status=ok", status_code=302)

        conn.execute(
            "INSERT INTO subscribers (email, subscribed_at, source, ip_hash) VALUES (?, ?, ?, ?)",
            (email, datetime.now(timezone.utc).isoformat(), source[:50], ip_hash)
        )

    print(f"[newsletter] New subscriber: {email[:4]}***@{email.split('@')[1]} (source={source})")

    if redirect == "0":
        return JSONResponse({"ok": True, "status": "subscribed"})
    return RedirectResponse(f"{THANK_YOU_URL}?status=ok", status_code=302)


@app.get("/subscribe/count")
async def subscriber_count():
    """Public count of confirmed + unconfirmed subscribers."""
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) FROM subscribers").fetchone()
    return {"count": row[0]}


@app.get("/admin/subscribers")
async def list_subscribers(key: str = "", format: str = "json"):
    """Export subscriber list (requires NEWSLETTER_KEY)."""
    if not API_KEY or key != API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT email, subscribed_at, source, confirmed FROM subscribers ORDER BY subscribed_at DESC"
        ).fetchall()
    data = [dict(r) for r in rows]
    if format == "csv":
        lines = ["email,subscribed_at,source,confirmed"]
        for r in data:
            lines.append(f"{r['email']},{r['subscribed_at']},{r['source']},{r['confirmed']}")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("\n".join(lines), media_type="text/csv")
    return JSONResponse({"total": len(data), "subscribers": data})


@app.get("/health")
async def health():
    return {"ok": True}
