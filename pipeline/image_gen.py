"""
Article Image Generator — generates editorial header images via Kie.ai Z-Image API.
Cost: ~$0.004/image (10x cheaper than Nano Banana 2).

Hardening:
- PER_ARTICLE_TIMEOUT: 90s (threading.Timer, works in all contexts)
- CIRCUIT_BREAKER_THRESHOLD: 1 consecutive failure trips the breaker
- MAX_TOTAL_SEC: 300s hard cap on entire batch (overridable via generate_images_for_articles)
"""
import os
import json
import time
import threading
import urllib.request
import urllib.error
from typing import Any, List, Dict, Optional

KIE_API_KEY = os.environ.get("KIE_API_KEY", "")
KIE_BASE_URL = "https://api.kie.ai"
IMAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "images", "articles")

PER_ARTICLE_TIMEOUT = 90     # seconds — if Kie.ai hasn't responded, it won't
MAX_TOTAL_SEC = 300           # seconds — hard cap on entire image_gen call
CIRCUIT_BREAKER_THRESHOLD = 1  # consecutive failures before giving up the whole batch


def _kie_request(endpoint: str, data: dict) -> dict:
    """Make a POST request to Kie.ai API."""
    url = f"{KIE_BASE_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {KIE_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST",
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


def _poll_task_with_timeout(task_id: str, timeout_sec: int = PER_ARTICLE_TIMEOUT) -> Optional[str]:
    """Poll for task completion with a hard wall-clock timeout via threading.Timer.

    Returns image URL or None.
    """
    result_holder: List[Optional[str]] = [None]
    done_event = threading.Event()

    def _poll():
        start = time.time()
        while not done_event.is_set():
            if time.time() - start >= timeout_sec:
                print(f"[image_gen] Task {task_id} poll loop timed out ({timeout_sec}s)")
                done_event.set()
                return
            try:
                result = _kie_get("/api/v1/jobs/recordInfo", {"taskId": task_id})
                state = result.get("data", {}).get("state", "")
                if state == "success":
                    rj = json.loads(result["data"]["resultJson"])
                    urls = rj.get("resultUrls", [])
                    result_holder[0] = urls[0] if urls else None
                    done_event.set()
                    return
                elif state == "fail":
                    print(f"[image_gen] Task {task_id} failed: {result['data'].get('failMsg', 'unknown')}")
                    done_event.set()
                    return
            except Exception as e:
                if not done_event.is_set():
                    print(f"[image_gen] Poll error: {e}")
            if not done_event.is_set():
                time.sleep(5)

    # Start poll thread
    poll_thread = threading.Thread(target=_poll, daemon=True)
    poll_thread.start()

    # Timer to force-cancel after timeout
    def _timeout_trigger():
        if not done_event.is_set():
            print(f"[image_gen] Hard timeout ({timeout_sec}s) for task {task_id}")
            done_event.set()

    timer = threading.Timer(timeout_sec, _timeout_trigger)
    timer.start()

    done_event.wait(timeout=timeout_sec + 2)  # extra 2s grace
    timer.cancel()

    return result_holder[0]


def _build_alt_text(title: str, category: str) -> str:
    """Generate alt text for a featured image — just the article title."""
    return title[:125]


def _build_generation_prompt(title: str, category: str, intent: dict[str, Any] | None = None) -> str:
    intent = intent or {}
    style_hints = {
        "Kotimaa": "Finnish landscape elements, blue and white tones, Nordic architecture",
        "Ulkomaat": "global perspective, world map elements, international context",
        "Talous": "financial charts, business district, economic graphs",
        "Teknologia": "circuit boards, digital interfaces, futuristic tech",
        "Urheilu": "dynamic sports action, stadium, athletic energy",
        "Kulttuuri": "art gallery, musical instruments, theater, creative expression",
        "Tiede": "laboratory, molecular structures, space, scientific instruments",
    }
    style = style_hints.get(category, "editorial newspaper illustration")
    must_have = ", ".join(intent.get("must_have") or [])
    must_not = ", ".join(intent.get("must_not") or [])
    safety = intent.get("safety_mode") or "normal"
    safety_clause = (
        "Use a non-photorealistic editorial illustration. Do not depict a real person's likeness, "
        "victims, crime scenes, attack scenes, disaster scenes, logos, brand marks, or readable text. "
        if safety == "illustration_only"
        else "Use an editorial illustration style, not a fake documentary photo. No text, logos, or watermarks. "
    )
    cue_clause = f"Required visual cues: {must_have}. " if must_have else ""
    avoid_clause = f"Avoid: {must_not}. " if must_not else ""
    return (
        f"Editorial newspaper header illustration for a Finnish news article titled '{title}'. "
        f"{safety_clause}"
        f"Visual subject: {intent.get('subject') or title}. "
        f"Setting: {intent.get('setting') or style}. "
        f"{cue_clause}{avoid_clause}"
        f"Style: modern, clean, professional, muted sophisticated palette. "
        f"Widescreen 16:9 composition suitable as a news article banner."
    )


def generate_article_image(
    title: str,
    category: str,
    slug: str,
    *,
    intent: dict[str, Any] | None = None,
) -> Optional[str]:
    """Generate a header image for an article. Returns relative path or None."""
    os.makedirs(IMAGE_DIR, exist_ok=True)

    filepath = os.path.join(IMAGE_DIR, f"{slug}.jpg")
    webpath = f"/images/articles/{slug}.jpg"

    if os.path.exists(filepath):
        return webpath

    prompt = _build_generation_prompt(title, category, intent)

    try:
        result = _kie_request("/api/v1/jobs/createTask", {
            "model": "z-image",
            "input": {
                "prompt": prompt,
                "aspect_ratio": "16:9",
                "output_format": "jpg"
            }
        })

        task_id = result.get("data", {}).get("taskId")
        if not task_id:
            print(f"[image_gen] No taskId returned for '{title[:40]}'")
            return None

        print(f"[image_gen] Task {task_id} for '{title[:40]}'")

        image_url = _poll_task_with_timeout(task_id, timeout_sec=PER_ARTICLE_TIMEOUT)
        if not image_url:
            return None

        urllib.request.urlretrieve(image_url, filepath)
        size = os.path.getsize(filepath)
        print(f"[image_gen] Downloaded {slug}.jpg ({size} bytes)")
        return webpath

    except Exception as e:
        print(f"[image_gen] Error generating image for '{title[:40]}': {e}")
        return None


def generate_images_for_articles(articles: List[Dict], max_total_sec: int = MAX_TOTAL_SEC) -> List[Dict]:
    """Generate header images for a list of articles.

    Args:
        articles: List of article dicts to process.
        max_total_sec: Hard cap on total wall-clock time for the entire batch.

    Circuit breaker: if CIRCUIT_BREAKER_THRESHOLD consecutive articles fail,
    skip the rest (API is probably down).
    """
    step_start = time.time()
    consecutive_failures = 0

    for i, article in enumerate(articles):
        # Hard total budget check
        elapsed = time.time() - step_start
        if elapsed >= max_total_sec:
            remaining = len(articles) - i
            print(f"[image_gen] Total budget {max_total_sec}s exhausted after {elapsed:.0f}s. "
                  f"Skipping {remaining} remaining articles.")
            break

        # Circuit breaker
        if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
            print(f"[image_gen] Circuit breaker tripped ({consecutive_failures} consecutive failures). "
                  f"Skipping remaining {len(articles) - i} articles.")
            break

        title = article.get("title", "")
        category = article.get("category", "")
        slug = article.get("slug", "")
        if not slug:
            import re
            import unicodedata
            slug = unicodedata.normalize('NFKD', title.lower())
            slug = slug.replace('ä', 'a').replace('ö', 'o').replace('å', 'a')
            slug = re.sub(r'[^a-z0-9\s-]', '', slug)
            slug = re.sub(r'[\s-]+', '-', slug).strip('-')[:60].rstrip('-')

        try:
            from image_candidate_guard import build_image_intent
            key_points = list(article.get("key_points") or [])
            key_points.extend(article.get("tags") or [])
            intent = build_image_intent(
                title,
                category,
                summary=article.get("summary", "") or "",
                key_points=key_points,
                content=article.get("content", "") or "",
            ).to_dict()
        except Exception:
            intent = {}

        if intent and not intent.get("generated_ok", True):
            print(f"[image_gen] Generated fallback unsafe for '{title[:40]}'")
            consecutive_failures += 1
            continue

        image_path = generate_article_image(title, category, slug, intent=intent)
        if image_path:
            article["image"] = image_path
            article["image_alt"] = _build_alt_text(title, category)
            article["image_thumb"] = image_path
            article["image_credit"] = ""
            article["image_source_url"] = ""
            article["image_caption"] = ""
            article["image_hotlink"] = False
            article["image_category_fallback"] = False
            article["image_source"] = "generated"
            article["image_source_type"] = "generated_editorial"
            article["image_decision_reason"] = "stock candidates unavailable or rejected"
            article["image_generated_fallback"] = True
            article["image_visual_intent"] = intent
            article["image_decision"] = {
                "source": "generated",
                "accepted": True,
                "reason": "stock candidates unavailable or rejected",
                "safety_mode": intent.get("safety_mode") if intent else "normal",
            }
            consecutive_failures = 0  # reset on success
        else:
            consecutive_failures += 1
            print(f"[image_gen] Failure #{consecutive_failures} (consecutive) for '{title[:40]}'")

        # Rate limit — skip after last article
        if i < len(articles) - 1:
            time.sleep(2)

    return articles
