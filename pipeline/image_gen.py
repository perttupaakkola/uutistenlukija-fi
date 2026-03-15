"""
Article Image Generator — generates editorial header images via Kie.ai Nano Banana 2 API.
"""
import os
import json
import time
import urllib.request
import urllib.error
from typing import List, Dict, Optional

KIE_API_KEY = os.environ.get("KIE_API_KEY", "bccd653c94693baab42985f14ec4a9dd")
KIE_BASE_URL = "https://api.kie.ai"
IMAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "images", "articles")


def _kie_request(endpoint: str, data: dict) -> dict:
    """Make a request to Kie.ai API."""
    url = f"{KIE_BASE_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {KIE_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST" if data else "GET"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _kie_get(endpoint: str, params: dict = None) -> dict:
    """GET request to Kie.ai API."""
    url = f"{KIE_BASE_URL}{endpoint}"
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {KIE_API_KEY}"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _poll_task(task_id: str, max_wait: int = 120) -> Optional[str]:
    """Poll for task completion, return image URL or None."""
    start = time.time()
    while time.time() - start < max_wait:
        try:
            result = _kie_get("/api/v1/jobs/recordInfo", {"taskId": task_id})
            state = result.get("data", {}).get("state", "")
            if state == "success":
                rj = json.loads(result["data"]["resultJson"])
                urls = rj.get("resultUrls", [])
                return urls[0] if urls else None
            elif state == "fail":
                print(f"[image_gen] Task {task_id} failed: {result['data'].get('failMsg', 'unknown')}")
                return None
        except Exception as e:
            print(f"[image_gen] Poll error: {e}")
        time.sleep(5)
    print(f"[image_gen] Task {task_id} timed out after {max_wait}s")
    return None


def generate_article_image(title: str, category: str, slug: str) -> Optional[str]:
    """Generate a header image for an article. Returns the relative path or None."""
    os.makedirs(IMAGE_DIR, exist_ok=True)

    filepath = os.path.join(IMAGE_DIR, f"{slug}.jpg")
    webpath = f"/images/articles/{slug}.jpg"

    # Skip if already exists
    if os.path.exists(filepath):
        return webpath

    # Category-specific style hints
    style_hints = {
        "Kotimaa": "Finnish landscape elements, blue and white tones, Nordic architecture",
        "Ulkomaat": "global perspective, world map elements, international flags",
        "Talous": "financial charts, business district, economic graphs",
        "Teknologia": "circuit boards, digital interfaces, futuristic tech",
        "Urheilu": "dynamic sports action, stadium, athletic energy",
        "Kulttuuri": "art gallery, musical instruments, theater, creative expression",
        "Tiede": "laboratory, molecular structures, space, scientific instruments",
    }

    style = style_hints.get(category, "editorial newspaper illustration")

    prompt = f"Editorial newspaper header illustration for a Finnish news article titled '{title}'. Style: modern editorial illustration, clean and professional, muted sophisticated color palette. Visual theme: {style}. No text in the image. Widescreen composition, suitable as a news article banner."

    try:
        result = _kie_request("/api/v1/jobs/createTask", {
            "model": "nano-banana-2",
            "input": {
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "resolution": "1K",
                "output_format": "jpg"
            }
        })

        task_id = result.get("data", {}).get("taskId")
        if not task_id:
            print(f"[image_gen] No taskId returned for '{title[:40]}...'")
            return None

        print(f"[image_gen] Task {task_id} for '{title[:40]}...'")

        image_url = _poll_task(task_id)
        if not image_url:
            return None

        # Download
        urllib.request.urlretrieve(image_url, filepath)
        size = os.path.getsize(filepath)
        print(f"[image_gen] Downloaded {slug}.jpg ({size} bytes)")
        return webpath

    except Exception as e:
        print(f"[image_gen] Error generating image for '{title[:40]}...': {e}")
        return None


def generate_images_for_articles(articles: List[Dict]) -> List[Dict]:
    """Generate header images for a list of articles. Adds 'image' field."""
    for i, article in enumerate(articles):
        title = article.get("title", "")
        category = article.get("category", "")
        # Create slug from title
        slug = article.get("slug", "")
        if not slug:
            import re
            import unicodedata
            slug = unicodedata.normalize('NFKD', title.lower())
            slug = slug.replace('ä', 'a').replace('ö', 'o').replace('å', 'a')
            slug = re.sub(r'[^a-z0-9\s-]', '', slug)
            slug = re.sub(r'[\s-]+', '-', slug).strip('-')[:60].rstrip('-')

        image_path = generate_article_image(title, category, slug)
        if image_path:
            article["image"] = image_path

        # Rate limit: 2 second sleep between requests (skip after last)
        if i < len(articles) - 1:
            time.sleep(2)

    return articles
