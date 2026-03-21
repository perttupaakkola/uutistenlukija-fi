"""
Publisher — saves rewritten articles as Hugo content files and builds the site.
"""

import os
import subprocess
from datetime import datetime, timezone
from typing import List, Dict

import re
import unicodedata

from writers import assign_writer


CONTENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content", "posts")
SITE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HUGO_BIN = os.environ.get("HUGO_BIN", "/workspace/hugo")


def _make_slug(title: str, max_length: int = 60) -> str:
    """Create a URL-friendly slug from title."""
    # Normalize unicode, convert Finnish chars
    slug = unicodedata.normalize('NFKD', title.lower())
    slug = slug.replace('ä', 'a').replace('ö', 'o').replace('å', 'a')
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug).strip('-')
    return slug[:max_length].rstrip('-')


def _article_to_markdown(article: Dict, date: str) -> str:
    """Convert article to Hugo markdown with front matter."""
    title = article.get("title", "Untitled")
    # Sanitize: collapse whitespace/newlines, escape double-quotes for YAML inline string
    title = " ".join(title.split())
    title = title.replace('"', '\\"')
    category = article.get("category", "Kotimaa")
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
    description_line = f'\ndescription: "{_esc(description)}"' if description else ""

    # Build front matter — no source_name or source_url
    front_matter = f"""---
title: "{title}"
date: {date}
categories:
  - {category}
author: "{writer['name']}"
author_id: "{writer['id']}"
author_title: "{writer['title']}"
author_bio: "{writer['bio']}"
author_image: "{writer['image']}"{description_line}{image_line}{image_thumb_line}{image_placeholder_line}{image_alt_line}{image_caption_line}{image_credit_line}{image_source_url_line}{trending_line}
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
