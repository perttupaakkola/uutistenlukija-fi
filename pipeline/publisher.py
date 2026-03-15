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
    """Convert a rewritten article to Hugo markdown with front matter."""
    title = article.get("title", "Untitled").replace('"', '\\"')
    category = article.get("category", "Kotimaa")
    source_name = article.get("source_name", "")
    source_url = article.get("source_url", "")
    content = article.get("content", "")

    # Assign a writer based on category
    writer = assign_writer(category)

    # Build front matter
    front_matter = f"""---
title: "{title}"
date: {date}
categories:
  - {category}
source_name: "{source_name}"
source_url: "{source_url}"
author: "{writer['name']}"
author_id: "{writer['id']}"
author_title: "{writer['title']}"
author_bio: "{writer['bio']}"
author_image: "{writer['image']}"
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


def build_site() -> bool:
    """Run hugo build to generate the static site."""
    try:
        result = subprocess.run(
            [HUGO_BIN, "--minify"],
            cwd=SITE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print(f"[publisher] Hugo build successful")
            if result.stderr:
                # Hugo outputs build info to stderr
                for line in result.stderr.strip().split("\n"):
                    print(f"[publisher]   {line}")
            return True
        else:
            print(f"[publisher] Hugo build failed:")
            print(result.stderr)
            return False
    except FileNotFoundError:
        print(f"[publisher] Hugo binary not found at {HUGO_BIN}")
        return False
    except Exception as e:
        print(f"[publisher] Build error: {e}")
        return False


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
