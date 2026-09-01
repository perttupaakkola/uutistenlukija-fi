"""
Article Image Generator — generates editorial header images via Kie.ai Z-Image API.
Cost: ~$0.004/image (10x cheaper than Nano Banana 2).

Hardening:
- PER_ARTICLE_TIMEOUT: 90s (threading.Timer, works in all contexts)
- CIRCUIT_BREAKER_THRESHOLD: 1 consecutive failure trips the breaker
- MAX_TOTAL_SEC: 300s hard cap on entire batch (overridable via generate_images_for_articles)
"""
import base64
import io
import json
import os
import socket
import time
import threading
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional

KIE_API_KEY = os.environ.get("KIE_API_KEY", "")
KIE_BASE_URL = "https://api.kie.ai"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE_DIR = os.path.join(PROJECT_ROOT, "static", "images", "articles")
REJECTED_IMAGE_DIR = os.path.join(
    PROJECT_ROOT,
    "pipeline",
    "rejected",
    "generated-images",
)

PER_ARTICLE_TIMEOUT = 90     # seconds — if Kie.ai hasn't responded, it won't
MAX_TOTAL_SEC = 300           # seconds — hard cap on entire image_gen call
CIRCUIT_BREAKER_THRESHOLD = 1  # consecutive failures before giving up the whole batch
IMAGE_DOWNLOAD_MAX_BYTES = 20 * 1024 * 1024
IMAGE_DOWNLOAD_USER_AGENT = "uutistenlukija-image-fetch/1.0"
TRANSIENT_POLL_HTTP_STATUS = frozenset({408, 425, 429})
POLL_INTERVAL_SEC = 5
IMAGE_TERMINAL_SCHEMA = "uutistenlukija.image_terminal.v1"
GENERATION_TERMINAL_FIELD = "image_generation_terminal"
IMAGE_TERMINAL_REASONS_FIELD = "image_terminal_reasons"
PIXEL_ANALYZER_MODEL = "gpt-4o-mini"
PIXEL_ANALYZER_MAX_EDGE = 1024
PIXEL_ANALYZER_TIMEOUT_SEC = 30

REASON_ACCEPTED = "accepted"
REASON_STOCK_REJECTION = "stock_rejection"
REASON_KEY_UNAVAILABLE = "key_unavailable"
REASON_BACKOFF = "backoff"
REASON_PROVIDER_HTTP = "provider_http_status"
REASON_PROVIDER_RUNTIME = "provider_runtime_fault"
REASON_TIMEOUT = "timeout"
REASON_PRE_SAFETY_REJECT = "pre_safety_reject"
REASON_VISUAL_REJECT = "visual_reject"
REASON_CATEGORY_FALLBACK = "category_fallback"


@dataclass(frozen=True)
class GeneratedImageResult:
    """One non-secret generated-image outcome.

    ``raster_properties`` contains objective format/dimension diagnostics.
    ``pixel_semantics`` is a legacy compatibility field and is never trusted by
    the publish gate. The gate invokes its own analyzer over the local decoded
    raster so callers cannot inject prompt, filename, URL, or metadata hints.
    """

    image_path: Optional[str]
    prompt: str
    terminal: dict[str, Any]
    raster_properties: dict[str, Any] = field(default_factory=dict)
    pixel_semantics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _PollResult:
    image_url: Optional[str]
    reason: str = ""
    provider_fault: bool = False
    http_status_class: Optional[str] = None


def build_image_terminal_reason(
    *,
    stage: str,
    reason: str,
    outcome: str,
    provider_fault: bool = False,
    provider_attempted: bool = False,
    provider_succeeded: bool = False,
    http_status_class: Optional[str] = None,
    provider: str = "",
) -> dict[str, Any]:
    """Return a stable, non-secret image terminal record."""
    result: dict[str, Any] = {
        "schema": IMAGE_TERMINAL_SCHEMA,
        "stage": stage,
        "reason": reason,
        "outcome": outcome,
        "provider_fault": bool(provider_fault),
        "provider_attempted": bool(provider_attempted),
        "provider_succeeded": bool(provider_succeeded),
    }
    if http_status_class:
        result["http_status_class"] = http_status_class
    if provider:
        result["provider"] = provider
    return result


def append_image_terminal_reason(article: dict[str, Any], terminal: dict[str, Any]) -> None:
    """Append one deduplicated terminal record to an article."""
    existing = list(article.get(IMAGE_TERMINAL_REASONS_FIELD) or [])
    identity = (
        terminal.get("stage"),
        terminal.get("provider"),
        terminal.get("reason"),
        terminal.get("outcome"),
        terminal.get("http_status_class"),
    )
    if not any(
        (
            row.get("stage"),
            row.get("provider"),
            row.get("reason"),
            row.get("outcome"),
            row.get("http_status_class"),
        ) == identity
        for row in existing
        if isinstance(row, dict)
    ):
        existing.append(dict(terminal))
    article[IMAGE_TERMINAL_REASONS_FIELD] = existing


def set_generation_terminal(article: dict[str, Any], terminal: dict[str, Any]) -> None:
    """Persist the generated stage result and its cross-stage trace."""
    article[GENERATION_TERMINAL_FIELD] = dict(terminal)
    append_image_terminal_reason(article, terminal)


def _http_status_class(status: int) -> str:
    if 100 <= int(status) <= 599:
        return f"{int(status) // 100}xx"
    return "unknown"


def _provider_error_terminal(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, urllib.error.HTTPError):
        return build_image_terminal_reason(
            stage="generated",
            reason=REASON_PROVIDER_HTTP,
            outcome="provider_fault",
            provider_fault=True,
            provider_attempted=True,
            http_status_class=_http_status_class(exc.code),
        )
    if isinstance(exc, (TimeoutError, socket.timeout)):
        reason = REASON_TIMEOUT
    elif isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, (TimeoutError, socket.timeout)):
        reason = REASON_TIMEOUT
    else:
        reason = REASON_PROVIDER_RUNTIME
    return build_image_terminal_reason(
        stage="generated",
        reason=reason,
        outcome="provider_fault",
        provider_fault=True,
        provider_attempted=True,
    )


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


def _image_extension(content_type: str, prefix: bytes) -> Optional[str]:
    """Return a safe extension for a validated provider image payload."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized and not normalized.startswith("image/"):
        return None
    if prefix.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(prefix) >= 12 and prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
        return ".webp"
    return None


def _inspect_generated_image(filepath: str) -> dict[str, Any]:
    """Validate one raster and return only objective properties.

    EXIF and ``Image.info`` text are controlled by the image provider. They are
    deliberately ignored because they cannot authorize unrelated pixels. The
    separate pixel analyzer receives a decoded, metadata-free raster.
    """
    try:
        from PIL import Image

        with Image.open(filepath) as image:
            observed: dict[str, Any] = {
                "image_format": str(image.format or "").lower(),
                "image_width": int(image.width),
                "image_height": int(image.height),
            }
            image.verify()

        return observed
    except Exception as exc:
        print(
            "[image_gen] Generated image metadata unavailable "
            f"type={exc.__class__.__name__}"
        )
        return {}


def _analyze_generated_pixels(filepath: str) -> dict[str, str]:
    """Describe depicted content from a decoded, metadata-free raster.

    The analyzer receives no filename, URL, article text, prompt, or provider
    metadata. Any decode, credential, transport, or response failure propagates
    to the caller, which rejects the candidate.
    """
    from PIL import Image
    from openai import OpenAI

    with Image.open(filepath) as image:
        image.load()
        decoded = image.convert("RGB")
        decoded.thumbnail((PIXEL_ANALYZER_MAX_EDGE, PIXEL_ANALYZER_MAX_EDGE))
        payload = io.BytesIO()
        decoded.save(payload, format="JPEG", quality=85)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("pixel analyzer unavailable")

    encoded = base64.b64encode(payload.getvalue()).decode("ascii")
    response = OpenAI(
        api_key=api_key,
        timeout=PIXEL_ANALYZER_TIMEOUT_SEC,
        max_retries=0,
    ).chat.completions.create(
        model=PIXEL_ANALYZER_MODEL,
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Describe only the visible depicted content of this image. "
                        "Do not infer a filename, URL, prompt, article, identity, or event. "
                        "Return JSON with one non-empty string field named description."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                },
            ],
        }],
    )
    content = response.choices[0].message.content
    parsed = json.loads(content or "")
    description = parsed.get("description") if isinstance(parsed, dict) else None
    if not isinstance(description, str) or not description.strip():
        raise ValueError("pixel analyzer returned no description")
    return {"description": description.strip()[:1000]}


def _download_generated_image(image_url: str, output_stem: str) -> str:
    """Download a generated image with provider-compatible headers and validation."""
    req = urllib.request.Request(
        image_url,
        headers={
            "User-Agent": IMAGE_DOWNLOAD_USER_AGENT,
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.1",
        },
    )
    part_path = f"{output_stem}.part"
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            declared_length = resp.headers.get("Content-Length")
            if declared_length and int(declared_length) > IMAGE_DOWNLOAD_MAX_BYTES:
                raise ValueError(f"generated image exceeds {IMAGE_DOWNLOAD_MAX_BYTES} bytes")

            prefix = resp.read(64 * 1024)
            extension = _image_extension(resp.headers.get("Content-Type", ""), prefix)
            if not extension:
                raise ValueError("generated image response is not a supported image")

            total = len(prefix)
            if total > IMAGE_DOWNLOAD_MAX_BYTES:
                raise ValueError(f"generated image exceeds {IMAGE_DOWNLOAD_MAX_BYTES} bytes")
            with open(part_path, "wb") as handle:
                handle.write(prefix)
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > IMAGE_DOWNLOAD_MAX_BYTES:
                        raise ValueError(f"generated image exceeds {IMAGE_DOWNLOAD_MAX_BYTES} bytes")
                    handle.write(chunk)

        filepath = f"{output_stem}{extension}"
        os.replace(part_path, filepath)
        return filepath
    finally:
        if os.path.exists(part_path):
            os.remove(part_path)


def _is_transient_poll_http_status(status: int) -> bool:
    return int(status) in TRANSIENT_POLL_HTTP_STATUS or 500 <= int(status) <= 599


def _poll_task_with_timeout(task_id: str, timeout_sec: int = PER_ARTICLE_TIMEOUT) -> _PollResult:
    """Poll for task completion and preserve the typed terminal reason."""
    result_holder: List[_PollResult] = [
        _PollResult(None, reason=REASON_TIMEOUT, provider_fault=True)
    ]
    done_event = threading.Event()

    def _finish(result: _PollResult) -> None:
        if done_event.is_set():
            return
        result_holder[0] = result
        done_event.set()

    def _poll():
        deadline = time.monotonic() + timeout_sec
        while not done_event.is_set():
            if time.monotonic() >= deadline:
                print(f"[image_gen] Task {task_id} poll loop timed out ({timeout_sec}s)")
                _finish(_PollResult(None, reason=REASON_TIMEOUT, provider_fault=True))
                return
            try:
                result = _kie_get("/api/v1/jobs/recordInfo", {"taskId": task_id})
                state = result.get("data", {}).get("state", "")
                if state == "success":
                    rj = json.loads(result["data"]["resultJson"])
                    urls = rj.get("resultUrls", [])
                    if urls:
                        _finish(_PollResult(str(urls[0])))
                    else:
                        _finish(_PollResult(None, reason=REASON_PROVIDER_RUNTIME, provider_fault=True))
                    return
                elif state == "fail":
                    print(f"[image_gen] Task {task_id} failed with provider terminal state")
                    _finish(_PollResult(None, reason=REASON_PROVIDER_RUNTIME, provider_fault=True))
                    return
            except urllib.error.HTTPError as exc:
                status_class = _http_status_class(exc.code)
                if _is_transient_poll_http_status(exc.code):
                    print(
                        "[image_gen] Poll transient HTTP failure "
                        f"class={status_class}; retrying"
                    )
                else:
                    print(f"[image_gen] Poll permanent HTTP failure class={status_class}")
                    _finish(_PollResult(
                        None,
                        reason=REASON_PROVIDER_HTTP,
                        provider_fault=True,
                        http_status_class=status_class,
                    ))
                    return
            except (TimeoutError, socket.timeout):
                print("[image_gen] Poll request timed out; retrying")
            except urllib.error.URLError:
                print("[image_gen] Poll transient transport failure; retrying")
            except Exception as exc:
                print(f"[image_gen] Poll runtime failure type={exc.__class__.__name__}")
                _finish(_PollResult(None, reason=REASON_PROVIDER_RUNTIME, provider_fault=True))
                return
            if not done_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _finish(_PollResult(None, reason=REASON_TIMEOUT, provider_fault=True))
                    return
                time.sleep(min(POLL_INTERVAL_SEC, remaining))

    # Start poll thread
    poll_thread = threading.Thread(target=_poll, daemon=True)
    poll_thread.start()

    # Timer to force-cancel after timeout
    def _timeout_trigger():
        if not done_event.is_set():
            print(f"[image_gen] Hard timeout ({timeout_sec}s) for task {task_id}")
            _finish(_PollResult(None, reason=REASON_TIMEOUT, provider_fault=True))

    timer = threading.Timer(timeout_sec, _timeout_trigger)
    timer.start()

    done_event.wait(timeout=timeout_sec + 2)  # extra 2s grace
    timer.cancel()

    return result_holder[0]


def _generated_image_local_path(image_path: str) -> Optional[str]:
    """Resolve one generated web path inside IMAGE_DIR, rejecting traversal."""
    prefix = "/images/articles/"
    value = str(image_path or "")
    if not value.startswith(prefix):
        return None
    relative = value[len(prefix):]
    if not relative or os.path.basename(relative) != relative:
        return None
    root = os.path.realpath(IMAGE_DIR)
    candidate = os.path.realpath(os.path.join(root, relative))
    try:
        if os.path.commonpath([root, candidate]) != root:
            return None
    except ValueError:
        return None
    return candidate


def _quarantine_rejected_generated_image(image_path: str) -> bool:
    """Move one rejected generated asset out of the successful cache path."""
    local_path = _generated_image_local_path(image_path)
    if not local_path or not os.path.isfile(local_path):
        return False
    try:
        os.makedirs(REJECTED_IMAGE_DIR, exist_ok=True)
        quarantine_path = os.path.join(
            REJECTED_IMAGE_DIR,
            os.path.basename(local_path),
        )
        os.replace(local_path, quarantine_path)
        print(
            "[image_gen] Quarantined rejected generated image "
            f"{os.path.basename(local_path)}"
        )
        return True
    except OSError as exc:
        print(
            "[image_gen] Failed to quarantine rejected generated image "
            f"type={exc.__class__.__name__}"
        )
        try:
            os.remove(local_path)
            print(
                "[image_gen] Removed rejected generated image after "
                "quarantine failure"
            )
            return True
        except OSError as remove_exc:
            print(
                "[image_gen] Failed to remove rejected generated image "
                f"type={remove_exc.__class__.__name__}"
            )
            return False


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
) -> GeneratedImageResult:
    """Generate one header image and return a typed non-secret result."""
    os.makedirs(IMAGE_DIR, exist_ok=True)

    output_stem = os.path.join(IMAGE_DIR, slug)
    prompt = _build_generation_prompt(title, category, intent)
    for extension in (".jpg", ".png", ".webp"):
        filepath = f"{output_stem}{extension}"
        if os.path.exists(filepath):
            webpath = f"/images/articles/{slug}{extension}"
            return GeneratedImageResult(
                webpath,
                prompt,
                build_image_terminal_reason(
                    stage="generated",
                    reason=REASON_ACCEPTED,
                    outcome="accepted",
                ),
                raster_properties=_inspect_generated_image(filepath),
            )

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
            return GeneratedImageResult(
                None,
                prompt,
                build_image_terminal_reason(
                    stage="generated",
                    reason=REASON_PROVIDER_RUNTIME,
                    outcome="provider_fault",
                    provider_fault=True,
                    provider_attempted=True,
                ),
            )

        print(f"[image_gen] Task {task_id} for '{title[:40]}'")

        poll_result = _poll_task_with_timeout(task_id, timeout_sec=PER_ARTICLE_TIMEOUT)
        if not poll_result.image_url:
            return GeneratedImageResult(
                None,
                prompt,
                build_image_terminal_reason(
                    stage="generated",
                    reason=poll_result.reason or REASON_PROVIDER_RUNTIME,
                    outcome="provider_fault",
                    provider_fault=bool(poll_result.provider_fault),
                    provider_attempted=True,
                    http_status_class=poll_result.http_status_class,
                ),
            )

        filepath = _download_generated_image(poll_result.image_url, output_stem)
        webpath = f"/images/articles/{os.path.basename(filepath)}"
        size = os.path.getsize(filepath)
        print(f"[image_gen] Downloaded {os.path.basename(filepath)} ({size} bytes)")
        return GeneratedImageResult(
            webpath,
            prompt,
            build_image_terminal_reason(
                stage="generated",
                reason=REASON_ACCEPTED,
                outcome="accepted",
                provider_attempted=True,
                provider_succeeded=True,
            ),
            raster_properties=_inspect_generated_image(filepath),
        )

    except Exception as exc:
        terminal = _provider_error_terminal(exc)
        safe_class = terminal.get("http_status_class") or exc.__class__.__name__
        print(f"[image_gen] Generation provider failure for '{title[:40]}' type={safe_class}")
        return GeneratedImageResult(None, prompt, terminal)


def _coerce_generated_result(value: Any) -> GeneratedImageResult:
    """Keep legacy test/caller tuples fail-closed while migrating the API."""
    if isinstance(value, GeneratedImageResult):
        return value
    if isinstance(value, tuple) and len(value) == 2:
        image_path, prompt = value
        return GeneratedImageResult(
            str(image_path) if image_path else None,
            str(prompt or ""),
            build_image_terminal_reason(
                stage="generated",
                reason=REASON_ACCEPTED,
                outcome="accepted",
                provider_attempted=True,
                provider_succeeded=True,
            ),
        )
    return GeneratedImageResult(
        None,
        "",
        build_image_terminal_reason(
            stage="generated",
            reason=REASON_PROVIDER_RUNTIME,
            outcome="provider_fault",
            provider_fault=True,
            provider_attempted=True,
        ),
    )


def generate_images_for_articles(articles: List[Dict], max_total_sec: int = MAX_TOTAL_SEC) -> List[Dict]:
    """Generate header images for a list of articles.

    Args:
        articles: List of article dicts to process.
        max_total_sec: Hard cap on total wall-clock time for the entire batch.

    Circuit breaker: only consecutive provider/runtime faults trip it. Safety
    and visual-policy rejections remain fail-closed without poisoning provider
    health or blocking the next article.
    """
    step_start = time.time()
    consecutive_provider_failures = 0

    for i, article in enumerate(articles):
        # Hard total budget check
        elapsed = time.time() - step_start
        if elapsed >= max_total_sec:
            remaining = len(articles) - i
            print(f"[image_gen] Total budget {max_total_sec}s exhausted after {elapsed:.0f}s. "
                  f"Skipping {remaining} remaining articles.")
            for pending in articles[i:]:
                set_generation_terminal(
                    pending,
                    build_image_terminal_reason(
                        stage="generated",
                        reason=REASON_TIMEOUT,
                        outcome="skipped",
                    ),
                )
            break

        # Circuit breaker
        if consecutive_provider_failures >= CIRCUIT_BREAKER_THRESHOLD:
            print(f"[image_gen] Circuit breaker tripped ({consecutive_provider_failures} provider failures). "
                  f"Skipping remaining {len(articles) - i} articles.")
            for pending in articles[i:]:
                set_generation_terminal(
                    pending,
                    build_image_terminal_reason(
                        stage="generated",
                        reason=REASON_BACKOFF,
                        outcome="skipped",
                    ),
                )
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
            from image_candidate_guard import (
                build_visual_brief,
                generated_decision_fields,
                judge_visual_candidate,
            )
            key_points = list(article.get("key_points") or [])
            key_points.extend(article.get("tags") or [])
            brief = build_visual_brief(
                title,
                category,
                summary=article.get("summary", "") or "",
                key_points=key_points,
                content=article.get("content", "") or "",
            )
            intent = brief.intent.to_dict()
        except Exception as exc:
            print(f"[image_gen] Visual brief unavailable type={exc.__class__.__name__}")
            set_generation_terminal(
                article,
                build_image_terminal_reason(
                    stage="generated",
                    reason=REASON_PRE_SAFETY_REJECT,
                    outcome="policy_reject",
                ),
            )
            continue

        if not intent or not intent.get("generated_ok", True):
            print(f"[image_gen] Generated fallback unsafe for '{title[:40]}'")
            set_generation_terminal(
                article,
                build_image_terminal_reason(
                    stage="generated",
                    reason=REASON_PRE_SAFETY_REJECT,
                    outcome="policy_reject",
                ),
            )
            continue

        generated = _coerce_generated_result(
            generate_article_image(title, category, slug, intent=intent)
        )
        # Throttle every real provider attempt before any post-call branch can
        # continue to the next article. Cached images and pre-provider policy,
        # key, budget, or backoff terminals keep provider_attempted=false.
        if generated.terminal.get("provider_attempted") and i < len(articles) - 1:
            time.sleep(2)

        if not generated.image_path:
            set_generation_terminal(article, generated.terminal)
            if generated.terminal.get("provider_fault"):
                consecutive_provider_failures += 1
            print(
                f"[image_gen] Generated terminal for '{title[:40]}' "
                f"reason={generated.terminal.get('reason')}"
            )
            continue

        if generated.terminal.get("provider_succeeded"):
            consecutive_provider_failures = 0

        try:
            local_image_path = _generated_image_local_path(generated.image_path)
            if not local_image_path:
                raise ValueError("generated image path is not locally analyzable")
            pixel_semantics = _analyze_generated_pixels(local_image_path)
            judge = judge_visual_candidate(
                pixel_semantics,
                brief=brief,
                provider="generated",
            )
        except Exception as exc:
            print(f"[image_gen] Visual judge unavailable type={exc.__class__.__name__}")
            judge = {"score": 0, "accepted": False, "reasons": ["visual judge unavailable"]}

        judge_dict = judge.to_dict() if hasattr(judge, "to_dict") else dict(judge or {})
        if not bool(judge_dict.get("accepted")):
            terminal = build_image_terminal_reason(
                stage="generated",
                reason=REASON_VISUAL_REJECT,
                outcome="policy_reject",
                provider_attempted=bool(generated.terminal.get("provider_attempted")),
                provider_succeeded=bool(generated.terminal.get("provider_succeeded")),
            )
            terminal["visual_judge_score"] = judge_dict.get("score")
            terminal["visual_judge_hard_fail"] = bool(judge_dict.get("hard_fail"))
            set_generation_terminal(article, terminal)
            _quarantine_rejected_generated_image(generated.image_path)
            print(f"[image_gen] Generated image rejected by visual judge for '{title[:40]}'")
            continue

        image_path = generated.image_path
        article["image"] = image_path
        article["image_alt"] = _build_alt_text(title, category)
        article["image_thumb"] = image_path
        article["image_credit"] = ""
        article["image_source_url"] = ""
        article["image_caption"] = ""
        article["image_hotlink"] = False
        article["image_category_fallback"] = False
        article.update(generated_decision_fields(
            provider="kie.ai",
            model="z-image",
            prompt=generated.prompt,
            image_path=image_path,
            brief=brief,
            judge=judge,
            reason="stock candidates unavailable or rejected; KIE generated editorial fallback accepted",
        ))
        accepted_terminal = build_image_terminal_reason(
            stage="generated",
            reason=REASON_ACCEPTED,
            outcome="accepted",
            provider_attempted=bool(generated.terminal.get("provider_attempted")),
            provider_succeeded=bool(generated.terminal.get("provider_succeeded")),
        )
        set_generation_terminal(article, accepted_terminal)

    return articles
