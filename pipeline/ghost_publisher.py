"""Ghost CMS publisher — creates posts via Ghost Admin API.

Usage:
    from ghost_publisher import GhostPublisher
    gp = GhostPublisher()  # reads GHOST_API_URL + GHOST_ADMIN_API_KEY from env
    url = gp.publish(article_dict)

Article dict uses the same format as publisher.py outputs.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    import jwt  # PyJWT
except ImportError:
    jwt = None

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────

GHOST_API_URL = os.environ.get("GHOST_API_URL", "").rstrip("/")        # e.g. https://cms.uutistenlukija.fi
GHOST_ADMIN_API_KEY = os.environ.get("GHOST_ADMIN_API_KEY", "")        # id:secret format
GHOST_API_VERSION = "v5.0"


class GhostPublisherError(Exception):
    pass


class GhostPublisher:
    """Publish articles to Ghost CMS via Admin API."""

    def __init__(self, api_url: str = "", admin_key: str = ""):
        self.api_url = (api_url or GHOST_API_URL).rstrip("/")
        self.admin_key = admin_key or GHOST_ADMIN_API_KEY

        if not self.api_url:
            raise GhostPublisherError("GHOST_API_URL not set")
        if not self.admin_key:
            raise GhostPublisherError("GHOST_ADMIN_API_KEY not set (expected id:secret)")
        if ":" not in self.admin_key:
            raise GhostPublisherError("GHOST_ADMIN_API_KEY must be in id:secret format")

        self._key_id, self._key_secret = self.admin_key.split(":", 1)

    # ── JWT Auth ────────────────────────────────────────────────────────────

    def _make_token(self) -> str:
        """Create a short-lived JWT for Ghost Admin API."""
        if jwt is None:
            raise GhostPublisherError(
                "PyJWT not installed. Run: pip install PyJWT"
            )

        iat = int(time.time())
        header = {"alg": "HS256", "typ": "JWT", "kid": self._key_id}
        payload = {
            "iat": iat,
            "exp": iat + 300,  # 5 min
            "aud": f"/{GHOST_API_VERSION}/admin/",
        }
        return jwt.encode(
            payload,
            bytes.fromhex(self._key_secret),
            algorithm="HS256",
            headers=header,
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Ghost {self._make_token()}",
            "Content-Type": "application/json",
        }

    # ── API helpers ─────────────────────────────────────────────────────────

    def _api_post(self, endpoint: str, data: dict) -> dict:
        """POST to Ghost Admin API. Returns parsed JSON response."""
        url = f"{self.api_url}/ghost/api/{GHOST_API_VERSION}/admin/{endpoint}/"
        body = json.dumps(data).encode("utf-8")
        req = Request(url, data=body, headers=self._headers(), method="POST")

        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise GhostPublisherError(
                f"Ghost API {e.code}: {error_body[:500]}"
            ) from e

    def _upload_image(self, image_url: str) -> Optional[str]:
        """Upload an image to Ghost from URL. Returns Ghost-hosted URL or None."""
        try:
            # Download image
            with urlopen(image_url, timeout=15) as resp:
                img_data = resp.read()
                content_type = resp.headers.get("Content-Type", "image/jpeg")

            ext = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/avif": ".avif",
                "image/gif": ".gif",
            }.get(content_type, ".jpg")

            filename = f"pipeline-{int(time.time())}{ext}"

            # Ghost image upload uses multipart/form-data
            boundary = f"----GhostUpload{int(time.time())}"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8") + img_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

            url = f"{self.api_url}/ghost/api/{GHOST_API_VERSION}/admin/images/upload/"
            headers = self._headers()
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            req = Request(url, data=body, headers=headers, method="POST")

            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("images", [{}])[0].get("url")

        except Exception as e:
            logger.warning("Image upload failed for %s: %s", image_url, e)
            return None

    # ── Article → Ghost post mapping ────────────────────────────────────────

    def _article_to_post(self, article: Dict, publish: bool = False) -> dict:
        """Map pipeline article dict to Ghost post payload."""
        title = article.get("title", "Untitled")
        content = article.get("content", "")
        category = article.get("category", "")
        tags = article.get("tags", [])
        summary = article.get("summary", article.get("description", ""))
        image = article.get("image", "")
        source_name = article.get("source_name", article.get("source", ""))
        source_url = article.get("source_url", article.get("link", ""))

        # Wrap content in HTML if it looks like plain/markdown
        if content and not content.strip().startswith("<"):
            paragraphs = content.split("\n\n")
            content = "".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())

        # Source attribution footer
        if source_name:
            source_link = (
                f' <a href="{source_url}" target="_blank" rel="noopener nofollow">Lue alkuperäinen →</a>'
                if source_url else ""
            )
            content += (
                f'<div class="source-attribution">'
                f'<span>Alkuperäinen lähde: <strong>{source_name}</strong></span>'
                f'{source_link}</div>'
            )

        # Journalist note
        journalist_note = article.get("journalist_note", "")
        if journalist_note:
            content += (
                f'<aside class="journalist-note">'
                f'<strong>Toimittajan huomio</strong>'
                f'<p>{journalist_note}</p></aside>'
            )

        # Build tag objects — Ghost creates tags on the fly
        ghost_tags = []
        if category:
            ghost_tags.append({"name": category})
        for tag in tags[:10]:  # Ghost limit
            if tag.lower() != category.lower():
                ghost_tags.append({"name": tag})

        post = {
            "title": title,
            "html": content,
            "status": "published" if publish else "draft",
            "tags": ghost_tags,
            "custom_excerpt": summary[:300] if summary else None,
            "meta_title": title[:300],
            "meta_description": summary[:500] if summary else None,
        }

        # Featured image
        if image and image.startswith("http"):
            ghost_url = self._upload_image(image)
            if ghost_url:
                post["feature_image"] = ghost_url
                alt = article.get("image_alt", title)
                post["feature_image_alt"] = alt[:125]

        # Content type / analysis flag
        content_type = article.get("content_type", "article")
        if content_type == "analysis":
            post["tags"].insert(0, {"name": "#analysis"})  # internal tag

        return {k: v for k, v in post.items() if v is not None}

    # ── Public API ──────────────────────────────────────────────────────────

    def publish(self, article: Dict, publish: bool = False) -> str:
        """Create a Ghost post from an article. Returns the Ghost post URL.
        
        Args:
            article: Pipeline article dict (same format as publisher.py).
            publish: If True, set status to 'published'. Default is 'draft'.
        """
        post_data = self._article_to_post(article, publish=publish)
        logger.info("Publishing to Ghost: %s", post_data.get("title", "?")[:60])

        result = self._api_post("posts", {"posts": [post_data]})

        posts = result.get("posts", [])
        if not posts:
            raise GhostPublisherError(f"Ghost returned no posts: {result}")

        ghost_url = posts[0].get("url", "")
        ghost_id = posts[0].get("id", "")
        logger.info("Published: %s (id=%s)", ghost_url, ghost_id)
        return ghost_url

    def publish_batch(self, articles: list, publish: bool = False) -> list:
        """Create Ghost posts for multiple articles. Returns list of (title, url|error) tuples.
        
        Args:
            articles: List of pipeline article dicts.
            publish: If True, posts go live immediately. Default is 'draft'.
        """
        results = []
        for art in articles:
            title = art.get("title", "?")[:60]
            try:
                url = self.publish(art, publish=publish)
                results.append((title, url))
            except Exception as e:
                logger.error("Failed to publish '%s': %s", title, e)
                results.append((title, f"ERROR: {e}"))
        return results


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    """CLI: publish a JSON article file to Ghost."""
    import argparse

    parser = argparse.ArgumentParser(description="Publish articles to Ghost CMS")
    parser.add_argument("json_file", help="Path to JSON file with article(s)")
    parser.add_argument("--dry-run", action="store_true", help="Show post payload without publishing")
    parser.add_argument("--publish", action="store_true", help="Set status to 'published' (default is 'draft')")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    with open(args.json_file) as f:
        data = json.load(f)

    articles = data if isinstance(data, list) else [data]

    if args.dry_run:
        gp = GhostPublisher.__new__(GhostPublisher)
        gp.api_url = GHOST_API_URL or "https://example.com"
        gp.admin_key = "dry:run"
        gp._key_id = "dry"
        gp._key_secret = "00"
        # Stub image upload for dry run
        gp._upload_image = lambda url: url
        for art in articles:
            payload = gp._article_to_post(art)
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    gp = GhostPublisher()
    results = gp.publish_batch(articles, publish=args.publish)
    for title, url in results:
        status = "✅" if url.startswith("http") else "❌"
        print(f"  {status} {title}: {url}")


if __name__ == "__main__":
    main()
