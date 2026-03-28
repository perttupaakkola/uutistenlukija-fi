#!/usr/bin/env python3
"""
daily_briefing.py — build a Finnish daily newsletter preview from published articles.

Selects up to 5 newest non-draft articles from `content/posts/` for a target UTC day,
then renders a human-readable HTML preview for the day's email briefing.

Output:
    static/newsletter/daily-YYYY-MM-DD.html

Subject format:
    Päivän tärkeimmät – [date in Finnish]

Usage:
    python3 pipeline/daily_briefing.py
    python3 pipeline/daily_briefing.py --date 2026-03-25
    python3 pipeline/daily_briefing.py --dry-run

Cron (daily 17:00 UTC):
    0 17 * * * cd /home/pertt/.openclaw/workspace/projects/uutistenlukija && \
        python3 pipeline/daily_briefing.py >> pipeline/logs/daily-briefing.log 2>&1
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONTENT_DIR = PROJECT_DIR / "content" / "posts"
OUTPUT_DIR = PROJECT_DIR / "static" / "newsletter"
SITE_BASE_URL = "https://uutistenlukija.fi"
DEFAULT_LIMIT = 5
NEWSLETTER_UTM_SOURCE = "newsletter"
NEWSLETTER_UTM_MEDIUM = "email"
NEWSLETTER_UTM_CAMPAIGN = "daily_briefing"

MONTHS_FI = {
    1: "tammikuuta",
    2: "helmikuuta",
    3: "maaliskuuta",
    4: "huhtikuuta",
    5: "toukokuuta",
    6: "kesäkuuta",
    7: "heinäkuuta",
    8: "elokuuta",
    9: "syyskuuta",
    10: "lokakuuta",
    11: "marraskuuta",
    12: "joulukuuta",
}


@dataclass
class Article:
    title: str
    published_at: datetime
    description: str
    source_name: str
    source_domain: str
    category: str
    url: str
    body: str
    path: Path

    @property
    def blurb(self) -> str:
        return build_blurb(self.description, self.body)

    @property
    def source_label(self) -> str:
        return self.source_name or self.source_domain or "Uutistenlukija"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse simple YAML frontmatter without external deps."""
    meta: dict = {}
    body = text

    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not match:
        return meta, body

    fm_raw = match.group(1)
    body = match.group(2).strip()

    current_key = None
    list_buffer: list[str] = []

    def flush_list():
        nonlocal current_key, list_buffer
        if current_key is not None:
            meta[current_key] = list_buffer[:]
        current_key = None
        list_buffer = []

    for raw_line in fm_raw.splitlines():
        line = raw_line.rstrip()

        if re.match(r"^\s+-\s+", line):
            value = re.sub(r"^\s+-\s+", "", line).strip().strip('"\'')
            if current_key is not None:
                list_buffer.append(value)
            continue

        kv = re.match(r"^(\w[\w_-]*)\s*:\s*(.*)$", line)
        if not kv:
            continue

        flush_list()
        key = kv.group(1)
        value = kv.group(2).strip()

        if value == "":
            current_key = key
            list_buffer = []
            continue

        value = value.strip('"\'')
        lowered = value.lower()
        if lowered == "true":
            meta[key] = True
        elif lowered == "false":
            meta[key] = False
        else:
            meta[key] = value

    flush_list()
    return meta, body


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def slug_to_url(path: Path) -> str:
    return f"{SITE_BASE_URL}/posts/{path.stem}/"


def with_newsletter_utm(url: str, *, item_index: int | None = None) -> str:
    """Append newsletter attribution params so GA4 classifies traffic as Email."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({
        "utm_source": NEWSLETTER_UTM_SOURCE,
        "utm_medium": NEWSLETTER_UTM_MEDIUM,
        "utm_campaign": NEWSLETTER_UTM_CAMPAIGN,
    })
    if item_index is not None:
        query["utm_content"] = f"story_{item_index}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_markdown(text: str) -> str:
    text = normalize_space(text)
    text = re.sub(r"!?\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"[`*_>#~]", "", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    return normalize_space(text)


def first_sentence(text: str) -> str:
    text = strip_markdown(text)
    if not text:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    sentence = parts[0].strip()
    if sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def truncate_sentence(text: str, max_len: int = 180) -> str:
    text = normalize_space(text)
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    if not cut:
        cut = text[: max_len - 1]
    return cut + "…"


def build_blurb(description: str, body: str) -> str:
    candidate = first_sentence(description)
    if not candidate or len(candidate) < 24:
        candidate = first_sentence(body)
    if not candidate:
        candidate = "Lue päivän kärkijuttu Uutistenlukijasta."
    return truncate_sentence(candidate, max_len=180)


def load_daily_articles(target_day: date) -> list[Article]:
    articles: list[Article] = []

    for path in sorted(CONTENT_DIR.glob("**/*.md")):
        if path.name.startswith("_index"):
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        meta, body = parse_frontmatter(text)
        if meta.get("draft") is True:
            continue

        published_at = parse_iso_datetime(str(meta.get("date", "")))
        if not published_at or published_at.date() != target_day:
            continue

        categories = meta.get("categories", [])
        if isinstance(categories, str):
            categories = [categories]

        article = Article(
            title=normalize_space(str(meta.get("title", path.stem.replace("-", " ")))),
            published_at=published_at,
            description=normalize_space(str(meta.get("description", meta.get("summary", "")))),
            source_name=normalize_space(str(meta.get("source_name", ""))),
            source_domain=normalize_space(str(meta.get("source_domain", ""))),
            category=normalize_space(categories[0] if categories else "Uutiset"),
            url=slug_to_url(path),
            body=body,
            path=path,
        )
        articles.append(article)

    articles.sort(
        key=lambda a: (
            a.published_at,
            bool(a.description),
            bool(a.source_name or a.source_domain),
            len(a.body.split()),
        ),
        reverse=True,
    )
    return articles


def format_date_fi(target_day: date) -> str:
    return f"{target_day.day}. {MONTHS_FI[target_day.month]} {target_day.year}"


def build_subject(target_day: date) -> str:
    return f"Päivän tärkeimmät – {format_date_fi(target_day)}"


def build_output_path(target_day: date) -> Path:
    return OUTPUT_DIR / f"daily-{target_day.isoformat()}.html"


def render_html_preview(target_day: date, articles: list[Article], generated_at: datetime) -> str:
    subject = build_subject(target_day)
    generated_label = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    item_count = len(articles)

    rows = []
    for idx, article in enumerate(articles, start=1):
        tracked_url = with_newsletter_utm(article.url, item_index=idx)
        rows.append(
            f"""
            <li class=\"story\">
              <div class=\"story__number\">{idx}</div>
              <div class=\"story__content\">
                <div class=\"story__meta\">{html.escape(article.category)} · {html.escape(article.source_label)}</div>
                <h2 class=\"story__title\"><a href=\"{html.escape(tracked_url)}\">{html.escape(article.title)}</a></h2>
                <p class=\"story__blurb\">{html.escape(article.blurb)}</p>
                <p class=\"story__source\">Lähde: {html.escape(article.source_label)}</p>
              </div>
            </li>
            """.strip()
        )

    if not rows:
        rows.append(
            """
            <li class=\"story story--empty\">
              <div class=\"story__content\">
                <h2 class=\"story__title\">Ei vielä viittä juttua tälle päivälle</h2>
                <p class=\"story__blurb\">Kun päivän julkaisut karttuvat, tähän syntyy automaattisesti Päivän kooste -esikatselu.</p>
              </div>
            </li>
            """.strip()
        )

    return f"""<!doctype html>
<html lang=\"fi\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{html.escape(subject)}</title>
  <meta name=\"robots\" content=\"noindex, nofollow\">
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f6f3ee;
      --card: #ffffff;
      --text: #1f2933;
      --muted: #6b7280;
      --border: #e5dfd7;
      --accent: #c0392b;
      --accent-dark: #962d22;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #121212;
        --card: #1b1b1b;
        --text: #f1f1f1;
        --muted: #b5b5b5;
        --border: #2e2e2e;
        --accent: #e05a4d;
        --accent-dark: #f1776a;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 32px 16px;
    }}
    .wrap {{ max-width: 780px; margin: 0 auto; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 28px;
      box-shadow: 0 10px 30px rgba(0,0,0,.06);
    }}
    .eyebrow {{
      display: inline-block;
      color: var(--accent);
      font-size: 12px;
      letter-spacing: .08em;
      text-transform: uppercase;
      font-weight: 700;
      margin-bottom: 12px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: clamp(28px, 5vw, 42px);
      line-height: 1.15;
    }}
    .lede {{ margin: 0 0 10px; color: var(--muted); font-size: 17px; }}
    .meta {{ margin: 0; color: var(--muted); font-size: 14px; }}
    .subject {{
      margin: 24px 0 0;
      padding: 14px 16px;
      border-radius: 12px;
      background: color-mix(in srgb, var(--accent) 8%, var(--card) 92%);
      border: 1px solid color-mix(in srgb, var(--accent) 18%, var(--border) 82%);
      font-weight: 600;
    }}
    ol {{ list-style: none; padding: 0; margin: 28px 0 0; display: grid; gap: 14px; }}
    .story {{
      display: grid;
      grid-template-columns: 44px 1fr;
      gap: 14px;
      padding: 18px;
      border: 1px solid var(--border);
      border-radius: 14px;
      background: color-mix(in srgb, var(--card) 95%, var(--bg) 5%);
    }}
    .story__number {{
      width: 44px;
      height: 44px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--accent) 12%, var(--card) 88%);
      color: var(--accent-dark);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 18px;
    }}
    .story__meta, .story__source {{ color: var(--muted); font-size: 13px; }}
    .story__title {{ margin: 4px 0 8px; font-size: 22px; line-height: 1.25; }}
    .story__title a {{ color: inherit; text-decoration: none; }}
    .story__title a:hover {{ color: var(--accent); }}
    .story__blurb {{ margin: 0 0 8px; font-size: 16px; }}
    .footer {{ margin-top: 24px; color: var(--muted); font-size: 14px; }}
    .footer a {{ color: var(--accent); }}
    @media (max-width: 640px) {{
      .card {{ padding: 20px; border-radius: 14px; }}
      .story {{ grid-template-columns: 36px 1fr; padding: 16px; }}
      .story__number {{ width: 36px; height: 36px; font-size: 16px; }}
      .story__title {{ font-size: 19px; }}
    }}
  </style>
</head>
<body>
  <main class=\"wrap\">
    <article class=\"card\">
      <div class=\"eyebrow\">Päivän kooste</div>
      <h1>{html.escape(subject)}</h1>
      <p class=\"lede\">Päivän 5 tärkeintä juttua yhteen näkymään. Tiivis, selkeä, suomeksi.</p>
      <p class=\"meta\">Esikatselu generoitu {generated_label} · {item_count} juttua mukana</p>
      <p class=\"subject\">Aihe: {html.escape(subject)}</p>
      <ol>
        {''.join(rows)}
      </ol>
      <p class=\"footer\">Esikatselu käyttää julkaistuja artikkeleita hakemistosta <code>content/posts/</code>. Uutiset: <a href=\"{SITE_BASE_URL}\">{SITE_BASE_URL}</a></p>
    </article>
  </main>
</body>
</html>
"""


def build_plaintext_preview(target_day: date, articles: list[Article]) -> str:
    lines = [build_subject(target_day), ""]
    if not articles:
        lines.append("Ei vielä julkaistuja juttuja tälle päivälle.")
        return "\n".join(lines)

    for idx, article in enumerate(articles, start=1):
        lines.append(f"{idx}. {article.title}")
        lines.append(f"   {article.blurb} ({article.source_label})")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a daily Finnish newsletter preview from content/posts.")
    parser.add_argument("--date", dest="target_date", default="", help="Target UTC date (YYYY-MM-DD). Defaults to today UTC.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Max stories to include (default: {DEFAULT_LIMIT}).")
    parser.add_argument("--output", default="", help="Override output path. Defaults to static/newsletter/daily-YYYY-MM-DD.html")
    parser.add_argument("--dry-run", action="store_true", help="Print a plaintext preview instead of writing HTML.")
    return parser.parse_args()


def resolve_target_day(raw_value: str) -> date:
    if not raw_value:
        return datetime.now(timezone.utc).date()
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"Invalid --date '{raw_value}'. Use YYYY-MM-DD.") from exc


def main() -> int:
    args = parse_args()
    target_day = resolve_target_day(args.target_date)
    output_path = Path(args.output) if args.output else build_output_path(target_day)
    output_path = output_path if output_path.is_absolute() else (PROJECT_DIR / output_path)

    articles = load_daily_articles(target_day)[: max(1, args.limit)]

    if args.dry_run:
        print(build_plaintext_preview(target_day, articles))
        return 0

    html_preview = render_html_preview(target_day, articles, datetime.now(timezone.utc))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_preview, encoding="utf-8")

    print(f"[daily_briefing] Wrote {output_path}")
    print(f"[daily_briefing] Subject: {build_subject(target_day)}")
    print(f"[daily_briefing] Stories: {len(articles)}")
    if not articles:
        print("[daily_briefing] Warning: no same-day published articles found.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
