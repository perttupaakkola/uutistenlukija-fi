#!/usr/bin/env python3
"""
ghost_importer.py — Bulk-import Hugo articles into Ghost via Admin API.
Reads:  content/posts/**/*.md  (YAML frontmatter + markdown body)
Tracks: pipeline/logs/ghost-imported.json  (array of already-imported slugs)
Auth:   Ghost Admin API key (id:secret format), signed as HS256 JWT
Config: ghostUrl from hugo.toml (fallback http://localhost:2368)
Usage:
    python3 pipeline/ghost_importer.py --key <id:secret>
    python3 pipeline/ghost_importer.py --key <id:secret> --limit 100
    python3 pipeline/ghost_importer.py --key <id:secret> --dry-run
Environment:
    GHOST_ADMIN_KEY  — fallback if --key not supplied
"""
import argparse, base64, hashlib, hmac, json, os, re, sys, time
import urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR    = Path(__file__).parent
PROJECT_DIR   = SCRIPT_DIR.parent
CONTENT_DIR   = PROJECT_DIR / "content" / "posts"
IMPORTED_LOG  = SCRIPT_DIR / "logs" / "ghost-imported.json"
HUGO_TOML     = PROJECT_DIR / "hugo.toml"
MAX_LIMIT     = 200
DEFAULT_LIMIT = 50

def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def make_ghost_jwt(api_key):
    try:
        key_id, secret_hex = api_key.split(":", 1)
    except ValueError:
        raise ValueError("GHOST_ADMIN_KEY must be in 'id:secret' format")
    secret  = bytes.fromhex(secret_hex)
    now     = int(time.time())
    header  = _b64url(json.dumps({"alg":"HS256","typ":"JWT","kid":key_id}).encode())
    payload = _b64url(json.dumps({"iat":now,"exp":now+300,"aud":"/admin/"}).encode())
    sig     = hmac.new(secret, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(sig)}"

def read_ghost_url():
    if HUGO_TOML.exists():
        m = re.search(r'ghostUrl\s*=\s*["\']([^"\']+)["\']', HUGO_TOML.read_text())
        if m:
            return m.group(1).rstrip("/")
    return "http://localhost:2368"

def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body    = text[end+4:].strip()
    fm = {}
    for line in fm_text.splitlines():
        if ":" not in line: continue
        key, _, val = line.partition(":")
        key = key.strip(); val = val.strip().strip('"\'')
        if val.startswith("[") and val.endswith("]"):
            fm[key] = [v.strip().strip('"\'') for v in val[1:-1].split(",") if v.strip()]
        else:
            fm[key] = val
    return fm, body

def markdown_to_html(md):
    lines = md.splitlines(); html = []; in_para = False
    def flush():
        nonlocal in_para
        if in_para: html.append("</p>"); in_para = False
    def inline(s):
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.+?)\*",     r"<em>\1</em>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s
    for line in lines:
        s = line.strip()
        if not s: flush(); continue
        m = re.match(r"^(#{1,6})\s+(.+)$", s)
        if m:
            flush(); lvl = len(m.group(1))
            html.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>"); continue
        if re.match(r"^[-*_]{3,}$", s): flush(); html.append("<hr>"); continue
        if not in_para: html.append("<p>"); in_para = True
        else: html.append(" ")
        html.append(inline(s))
    flush()
    return "".join(html)

def load_imported():
    if IMPORTED_LOG.exists():
        try:
            data = json.loads(IMPORTED_LOG.read_text(encoding="utf-8"))
            return set(data if isinstance(data, list) else [])
        except Exception: pass
    return set()

def save_imported(slugs):
    IMPORTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    IMPORTED_LOG.write_text(
        json.dumps(sorted(slugs), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")

def ghost_request(method, url, token, body=None):
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization":  f"Ghost {token}",
        "Content-Type":   "application/json",
        "Accept-Version": "v5.0",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def create_post(ghost_url, token, post):
    resp = ghost_request("POST",
        f"{ghost_url}/ghost/api/admin/posts/?source=html",
        token, {"posts": [post]})
    return resp["posts"][0]["id"]

def load_articles(limit):
    articles = []
    if not CONTENT_DIR.exists():
        print(f"[ghost_importer] Content dir not found: {CONTENT_DIR}", file=sys.stderr)
        return []
    for md_path in CONTENT_DIR.glob("*.md"):
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
            fm, body = parse_frontmatter(text)
            if fm.get("draft", "false").lower() == "true": continue
            title = fm.get("title", "").strip()
            if not title: continue
            slug = md_path.stem
            raw_date = fm.get("date", "")
            try:
                if raw_date.endswith("Z"): raw_date = raw_date[:-1] + "+00:00"
                pub_dt = datetime.fromisoformat(raw_date)
            except Exception:
                pub_dt = datetime.now(timezone.utc)
            cats = fm.get("categories", [])
            if isinstance(cats, str): cats = [cats]
            tags = [{"name": c} for c in cats if c]
            excerpt = fm.get("description", "").strip()
            articles.append({
                "_slug": slug, "_pub_dt": pub_dt,
                "title": title, "slug": slug,
                "html": markdown_to_html(body),
                "status": "published",
                "published_at": pub_dt.isoformat(),
                "tags": tags,
                "custom_excerpt": excerpt or None,
            })
        except Exception as e:
            print(f"[ghost_importer] Warning: {md_path.name}: {e}", file=sys.stderr)
    articles.sort(key=lambda a: a["_pub_dt"], reverse=True)
    return articles[:limit]

def main():
    ap = argparse.ArgumentParser(description="Bulk-import Hugo articles into Ghost")
    ap.add_argument("--key",     default="")
    ap.add_argument("--url",     default="")
    ap.add_argument("--limit",   type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force",   action="store_true",
                    help="Re-import slugs already in ghost-imported.json")
    args = ap.parse_args()

    api_key   = args.key or os.environ.get("GHOST_ADMIN_KEY", "")
    if not api_key and not args.dry_run:
        print("[ghost_importer] ERROR: --key or GHOST_ADMIN_KEY required", file=sys.stderr)
        sys.exit(1)

    ghost_url = args.url or read_ghost_url()
    limit     = min(max(1, args.limit), MAX_LIMIT)
    print(f"[ghost_importer] Ghost: {ghost_url}  limit: {limit}  dry-run: {args.dry_run}")

    articles = load_articles(limit)
    if not articles:
        print("[ghost_importer] No articles found."); return

    imported = load_imported()
    print(f"[ghost_importer] {len(articles)} articles, {len(imported)} already imported")

    if args.dry_run:
        for i, a in enumerate(articles, 1):
            skip = " (skip)" if a["_slug"] in imported and not args.force else ""
            print(f"  {i:3}. [{a['_pub_dt'].strftime('%Y-%m-%d')}] {a['title'][:70]}{skip}")
        return

    token = make_ghost_jwt(api_key)
    ok = skip = errors = 0
    new_slugs: set = set()

    for i, a in enumerate(articles, 1):
        if a["_slug"] in imported and not args.force:
            skip += 1; continue
        post = {k: v for k, v in a.items()
                if not k.startswith("_") and v is not None}
        try:
            pid = create_post(ghost_url, token, post)
            print(f"[ghost_importer] ✅ ({i}) {a['title'][:60]} → {pid}")
            new_slugs.add(a["_slug"]); ok += 1
            if ok % 50 == 0:
                token = make_ghost_jwt(api_key)  # refresh before expiry
        except urllib.error.HTTPError as e:
            body = ""
            try: body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception: pass
            print(f"[ghost_importer] ❌ ({i}) {a['_slug']}: HTTP {e.code} — {body}",
                  file=sys.stderr)
            errors += 1
        except Exception as e:
            print(f"[ghost_importer] ❌ ({i}) {a['_slug']}: {e}", file=sys.stderr)
            errors += 1

    save_imported(imported | new_slugs)
    print(f"[ghost_importer] Done — ok:{ok} skipped:{skip} errors:{errors}")
    if errors:
        sys.exit(1)

if __name__ == "__main__":
    main()
