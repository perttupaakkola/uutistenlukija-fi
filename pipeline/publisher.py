"""
Publisher — saves rewritten articles as Hugo content files and builds the site.
"""

import os
import subprocess
from datetime import datetime, timezone
from typing import List, Dict
from pathlib import Path

import re
import unicodedata

from writers import assign_writer


CONTENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content", "posts")
SITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUGO_BIN = os.environ.get("HUGO_BIN", "/workspace/hugo")

TECH_CATEGORY_KEYWORDS = [
    "tekoäly", "ohjelmisto", "sovellus", "tietokone", "mobiili", "älypuhelin",
    "tietoturva", "kyberturvallisuus", "digitaalinen", "robotti", "automaatio",
    "pilvipalvelu", "startup", "teknologia",
]

SCIENCE_CATEGORY_KEYWORDS = [
    "tutkimus", "tiede", "tutkijat", "löytö", "avaruus", "ilmasto",
    "ilmastonmuutos", "evoluutio", "genomi", "DNA", "lääketiede",
]

WEATHER_KEYWORDS = [
    "sää", "sääennuste", "lämpötila", "sadealue", "tuulinen", "myrsky",
    "lumisade", "helle", "pakkanen", "ilmatieteen laitos", "säävaroitus",
    "ukkosmyrsky", "tuuli", "sade", "pilvisyys", "aurinkoinen",
]


def _keyword_score(text: str, keywords: list) -> int:
    """Count keyword matches in text (case-insensitive, word-boundary for 'AI')."""
    score = 0
    lowered = text.casefold()
    for keyword in keywords:
        folded = keyword.casefold()
        if keyword == "AI":
            if re.search(r"(?<![a-zåäö])ai(?![a-zåäö])", lowered, re.IGNORECASE):
                score += 1
            continue
        if folded in lowered:
            score += 1
    return score


def _apply_keyword_category_override(article: dict, category: str) -> str:
    """Override category based on keyword scoring.

    - Weather articles → Kotimaa (regardless of current category)
    - Kotimaa articles with tech/science keywords → Teknologia/Tiede
    """
    haystack = " ".join(
        str(article.get(field, "") or "")
        for field in ("title", "summary", "content")
    )
    if not haystack.strip():
        return category

    # Weather → Kotimaa (fires from any category, typically catches Tiede misclassification)
    weather_score = _keyword_score(haystack, WEATHER_KEYWORDS)
    if weather_score >= 2:
        raw_cat = str(article.get("category") or "").strip().lower()
        if raw_cat != "kotimaa":
            print(f"[publisher] Category override: {category} → Kotimaa (weather, score={weather_score})")
            return "Kotimaa"
        return category

    # Tech/Science override only fires when current category is Kotimaa or missing
    raw_category = str(article.get("category") or "").strip()
    if raw_category and raw_category.lower() != "kotimaa":
        return category

    tech_score = _keyword_score(haystack, TECH_CATEGORY_KEYWORDS + ["AI"])
    science_score = _keyword_score(haystack, SCIENCE_CATEGORY_KEYWORDS)

    if tech_score == 0 and science_score == 0:
        return category
    if science_score > tech_score:
        return "Tiede"
    return "Teknologia"


def _make_slug(title: str, max_length: int = 60) -> str:
    """Create a URL-friendly slug from title."""
    # Normalize unicode, convert Finnish chars
    slug = unicodedata.normalize('NFKD', title.lower())
    slug = slug.replace('ä', 'a').replace('ö', 'o').replace('å', 'a')
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug).strip('-')
    return slug[:max_length].rstrip('-')


def _split_front_matter(text: str) -> tuple[list[str], str]:
    """Return (front_matter_lines, body) for a Hugo markdown file."""
    if not text.startswith("---\n"):
        return [], text

    end = text.find("\n---\n", 4)
    if end == -1:
        return [], text

    front = text[4:end].splitlines()
    body = text[end + 5 :]
    return front, body


def _extract_front_matter_value(lines: list[str], key: str):
    prefix = f"{key}:"
    for idx, line in enumerate(lines):
        if line.startswith(prefix):
            raw = line[len(prefix):].strip()
            if raw.startswith('"') and raw.endswith('"'):
                return raw[1:-1]
            if raw.lower() == "true":
                return True
            if raw.lower() == "false":
                return False
            if raw:
                try:
                    return float(raw) if "." in raw else int(raw)
                except ValueError:
                    return raw

            values = []
            j = idx + 1
            while j < len(lines) and lines[j].startswith("  - "):
                values.append(lines[j][4:])
                j += 1
            return values
    return None


def _set_boolean_front_matter_flag(text: str, key: str, enabled: bool) -> str:
    lines, body = _split_front_matter(text)
    if not lines:
        return text

    filtered = [line for line in lines if not line.startswith(f"{key}:")]

    if enabled:
        insert_at = None
        for idx, line in enumerate(filtered):
            if line.startswith("draft:"):
                insert_at = idx
                break
        flag_line = f"{key}: true"
        if insert_at is None:
            filtered.append(flag_line)
        else:
            filtered.insert(insert_at, flag_line)

    front = "\n".join(filtered)
    body = body.lstrip("\n")
    return f"---\n{front}\n---\n\n{body}"


def _refresh_daily_briefing_flags(target_day: str) -> list[str]:
    """Assign briefing=true to up to 6 same-day articles, preferring category diversity.

    Selection order:
    1. Highest available score field (if any article has one)
    2. Otherwise newest first

    breaking=true articles are excluded.
    """
    posts_dir = Path(CONTENT_DIR)
    candidates: list[dict] = []

    for path in sorted(posts_dir.glob(f"{target_day}-*.md")):
        text = path.read_text(encoding="utf-8")
        lines, _body = _split_front_matter(text)
        if not lines:
            continue

        raw_date = str(_extract_front_matter_value(lines, "date") or "").strip()
        if not raw_date.startswith(target_day):
            continue
        if bool(_extract_front_matter_value(lines, "breaking") or False):
            continue

        categories = _extract_front_matter_value(lines, "categories") or []
        primary_category = str(categories[0]).strip().lower() if categories else "uutiset"

        score = None
        for key in ("editorial_score", "lead_score", "homepage_score", "score", "quality_score"):
            value = _extract_front_matter_value(lines, key)
            if isinstance(value, (int, float)):
                score = float(value)
                break
            if isinstance(value, str):
                try:
                    score = float(value.strip())
                    break
                except ValueError:
                    pass

        try:
            sort_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            sort_date = datetime.min.replace(tzinfo=timezone.utc)

        candidates.append({
            "path": path,
            "text": text,
            "category": primary_category,
            "score": score,
            "date": sort_date,
            "has_briefing": bool(_extract_front_matter_value(lines, "briefing") is True),
        })

    if not candidates:
        return []

    use_scores = any(item["score"] is not None for item in candidates)

    def _sort_key(item: dict):
        score_rank = item["score"] if item["score"] is not None else float("-inf")
        return (score_rank, item["date"].timestamp()) if use_scores else (item["date"].timestamp(),)

    ranked = sorted(candidates, key=_sort_key, reverse=True)
    selected: list[dict] = []
    seen_categories: set[str] = set()
    max_items = min(6, len(ranked))

    for item in ranked:
        if len(selected) >= max_items:
            break
        if item["category"] in seen_categories:
            continue
        selected.append(item)
        seen_categories.add(item["category"])

    if len(selected) < max_items:
        selected_paths = {item["path"] for item in selected}
        for item in ranked:
            if len(selected) >= max_items:
                break
            if item["path"] in selected_paths:
                continue
            selected.append(item)
            selected_paths.add(item["path"])

    selected_set = {item["path"] for item in selected}
    updated: list[str] = []

    for item in candidates:
        should_brief = item["path"] in selected_set
        if should_brief and item["has_briefing"]:
            continue
        if not should_brief and not item["has_briefing"]:
            continue

        new_text = _set_boolean_front_matter_flag(item["text"], "briefing", should_brief)
        item["path"].write_text(new_text, encoding="utf-8")
        updated.append(item["path"].name)

    print(
        f"[publisher] Briefing selection for {target_day}: "
        f"{len(selected_set)} articles (scores={'on' if use_scores else 'off'})"
    )
    return updated


def _article_to_markdown(article: Dict, date: str) -> str:
    """Convert article to Hugo markdown with front matter."""
    title = article.get("title", "Untitled")
    # Sanitize: collapse whitespace/newlines, escape double-quotes for YAML inline string
    title = " ".join(title.split())
    title = title.replace('"', '\\"')
    # Normalize category: match against canonical list (case-insensitive), fallback to Kotimaa
    _CANONICAL_CATEGORIES = ["Kotimaa", "Ulkomaat", "Talous", "Teknologia", "Urheilu", "Kulttuuri", "Tiede"]
    _raw_category = str(article.get("category", "") or "").strip()
    category = next(
        (c for c in _CANONICAL_CATEGORIES if c.lower() == _raw_category.lower()),
        "Kotimaa"  # fallback if LLM returns unknown value
    )
    category = _apply_keyword_category_override(article, category)
    content = article.get("content", "")
    # Sanitize content: strip bare YAML front matter delimiters (would break Hugo parsing)
    content = re.sub(r"(?m)^---+\s*$", "—", content)
    image = article.get("image", "")
    # Generate Finnish alt text from article context instead of stock photo title.
    # Format: "Kuvituskuva: {truncated article title}"
    # Fallback to category name when no image or title is unavailable.
    _raw_alt = article.get("image_alt", "")
    if image and title:
        # Truncate title to 80 chars so alt text stays concise
        _title_context = title[:80].rstrip()
        image_alt = f"Kuvituskuva: {_title_context}"
    elif image and category:
        image_alt = f"Kuvituskuva: {category}"
    elif _raw_alt:
        image_alt = _raw_alt
    else:
        image_alt = "Kuvituskuva"
    image_caption = article.get("image_caption", "")
    image_credit = article.get("image_credit", "")
    image_source_url = article.get("image_source_url", "")
    image_thumb = article.get("image_thumb", "")
    image_placeholder = article.get("image_placeholder", "")
    trending = article.get("trending", False)
    description = article.get("description", "")
    # Source attribution — source_url prefers original link over feed domain
    source_name = article.get("source", "")
    source_url = article.get("source_url", "") or article.get("link", "")
    source_domain = article.get("source_domain", "")
    summary = article.get("summary", "")
    tags = article.get("tags", [])
    key_points = article.get("key_points", [])
    journalist_note = article.get("journalist_note", "")
    content_type = article.get("content_type", "article")
    editorial_reviewed = bool(article.get("editorial_reviewed", True))

    # Reading time: Finnish reading speed 200 wpm + image viewing time
    # Images: 12s first, 10s second, -1s per subsequent image, 3s floor
    _word_count = len(re.findall(r"\S+", content))
    _reading_seconds = int((_word_count / 200) * 60)
    _image_count = len(re.findall(r"!\[", content))
    if image:
        _image_count += 1  # count hero image
    _image_seconds = sum(
        12 if i == 0 else max(3, 10 - (i - 1))
        for i in range(_image_count)
    )
    _total_seconds = _reading_seconds + _image_seconds
    # 0 = "alle 1 min"; stored as 0 so templates can show the Finnish label
    reading_time = 0 if _total_seconds < 45 else max(1, round(_total_seconds / 60))

    # Assign a writer based on category
    writer = assign_writer(category)

    def _esc(s: str) -> str:
        return s.replace('"', '\\"')

    # Build optional front matter fields
    image_line = f'\nimage: "{image}"' if image else ""
    image_alt_line = f'\nimage_alt: "{_esc(image_alt)}"' if image_alt else ""
    image_caption_line = f'\nimage_caption: "{_esc(image_caption)}"' if image_caption else ""
    image_credit_line = f'\nimage_credit: "{_esc(image_credit)}"' if image_credit else ""
    image_source_url_line = f'\nimage_source_url: "{image_source_url}"' if image_source_url else ""
    image_thumb_line = f'\nimage_thumb: "{image_thumb}"' if image_thumb else ""
    # base64 placeholder — use literal block scalar to avoid YAML line-length issues
    image_placeholder_line = f'\nimage_placeholder: "{image_placeholder}"' if image_placeholder else ""
    trending_line = "\ntrending: true" if trending else ""
    source_name_line = f'\nsource_name: "{_esc(source_name)}"' if source_name else ""
    source_url_line = f'\nsource_url: "{source_url}"' if source_url else ""
    source_domain_line = f'\nsource_domain: "{source_domain}"' if source_domain else ""
    reading_time_line = f"\nreading_time: {reading_time}"
    # Cap description at 155 chars for Google SERP display (truncates at ~160)
    if description and len(description) > 155:
        description = description[:152].rstrip() + "…"
    description_line = f'\ndescription: "{_esc(description)}"' if description else ""
    summary_line = f'\nsummary: "{_esc(summary)}"' if summary else ""
    if isinstance(key_points, list):
        key_points = [str(point).strip() for point in key_points if str(point).strip()]
    else:
        key_points = []
    key_points_yaml = "\nkey_points:\n" + "\n".join(f'  - "{_esc(point)}"' for point in key_points[:3]) if key_points else ""
    journalist_note_line = f'\njournalist_note: |\n  ' + '\n  '.join(str(journalist_note).splitlines()) if journalist_note else ""
    content_type = str(content_type or "article").strip().lower()
    if content_type not in {"article", "analysis"}:
        content_type = "article"
    content_type_line = f'\ncontent_type: "{content_type}"'
    type_line = '\ntype: "analysis"' if content_type == "analysis" else ""
    editorial_reviewed_line = "\neditorial_reviewed: true" if editorial_reviewed else "\neditorial_reviewed: false"
    if tags:
        tags_yaml = "\ntags:\n" + "\n".join(f'  - {_esc(str(t))}' for t in tags)
    else:
        tags_yaml = ""

    # Build SEO keywords from article-specific tags (concrete entities/topics)
    # Falls back to category-level keywords only if tags are empty
    seo_kws: List[str] = []
    if tags:
        seo_kws = [str(t).strip() for t in tags if str(t).strip()][:5]
    if not seo_kws:
        seo_keywords_path = Path(__file__).parent / "seo_keywords.json"
        try:
            import json as _json
            with open(seo_keywords_path) as _f:
                _kw_data = _json.load(_f)
            cat_data = _kw_data.get(category, {})
            seo_kws = cat_data.get("primary", [])[:3]
        except Exception:
            pass
    if seo_kws:
        keywords_yaml = "\nkeywords:\n" + "\n".join(f'  - "{_esc(str(k))}"' for k in seo_kws)
    else:
        keywords_yaml = ""

    # Build front matter — includes source attribution fields
    front_matter = f"""---
title: "{title}"
date: {date}
categories:
  - {category}
author: "{writer['name']}"
author_id: "{writer['id']}"
author_title: "{writer['title']}"
author_bio: "{writer['bio']}"
author_image: "{writer['image']}"{description_line}{summary_line}{key_points_yaml}{journalist_note_line}{content_type_line}{type_line}{editorial_reviewed_line}{image_line}{image_thumb_line}{image_placeholder_line}{image_alt_line}{image_caption_line}{image_credit_line}{image_source_url_line}{trending_line}{reading_time_line}{tags_yaml}{keywords_yaml}{source_name_line}{source_url_line}{source_domain_line}
draft: false
---

{content}
"""
    return front_matter


def publish_articles(articles: List[Dict]) -> List[str]:
    """Save articles as Hugo content files. Returns list of created file paths."""
    os.makedirs(CONTENT_DIR, exist_ok=True)
    created = []

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    for idx, article in enumerate(articles):
        slug = _make_slug(article.get("title", f"article-{idx}"))
        filename = f"{date_str}-{slug}.md"
        filepath = os.path.join(CONTENT_DIR, filename)

        # Use article date or now, offset by index to maintain order
        article_date = now.isoformat()
        markdown = _article_to_markdown(article, article_date)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(markdown)

        created.append(filepath)
        print(f"[publisher] Created: {filename}")

    updated = _refresh_daily_briefing_flags(date_str)
    if updated:
        print(f"[publisher] Updated briefing flags: {', '.join(updated)}")

    return created


def build_site() -> tuple[bool, str]:
    """Run hugo build to generate the static site.

    Returns (success, error_detail). error_detail is empty on success.
    Hugo mixes build info and errors across stdout/stderr, so both are
    captured and included in the error detail on failure.
    """
    try:
        result = subprocess.run(
            [HUGO_BIN, "--minify"],
            cwd=SITE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print("[publisher] Hugo build successful")
            if result.stderr:
                for line in result.stderr.strip().split("\n"):
                    print(f"[publisher]   {line}")
            return True, ""
        else:
            # Hugo can write error details to either stream — capture both
            out = result.stdout.strip()
            err = result.stderr.strip()
            combined = "\n".join(filter(None, [out, err])) or f"(exit code {result.returncode}, no output)"
            print(f"[publisher] Hugo build failed (exit {result.returncode}):")
            for line in combined.split("\n"):
                print(f"[publisher]   {line}")
            return False, combined
    except subprocess.TimeoutExpired:
        msg = "Hugo build timed out after 60s"
        print(f"[publisher] {msg}")
        return False, msg
    except FileNotFoundError:
        msg = f"Hugo binary not found at {HUGO_BIN}"
        print(f"[publisher] {msg}")
        return False, msg
    except Exception as e:
        msg = f"Build error: {e}"
        print(f"[publisher] {msg}")
        return False, msg


if __name__ == "__main__":
    # Test with sample data
    sample = [
        {
            "title": "Testiotsikko",
            "content": "Tämä on testisisältö.\n\nToinen kappale.",
            "category": "Kotimaa",
            "source_name": "Testi",
            "source_url": "https://example.com",
        }
    ]
    created = publish_articles(sample)
    print(f"Created {len(created)} files")
    build_site()
