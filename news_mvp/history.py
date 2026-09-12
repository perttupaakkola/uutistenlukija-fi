"""Selective public article data export. Never imports code, queues or agent state."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from .editorial import digest, web_url
from .intake import fetch


def preserve_article(source_file, public_url, state_dir):
    # PyYAML is already in the shared Hermes runtime; imported only for this
    # legacy public-data format. The controller/fixtures otherwise use stdlib.
    import yaml

    source_file = Path(source_file)
    if source_file.suffix != ".md" or source_file.stat().st_size > 200000:
        raise ValueError("Select one small published Markdown article")
    raw = source_file.read_bytes()
    content = raw.decode("utf-8")
    parts = content.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError("Expected YAML front matter")
    front = yaml.safe_load(parts[1])
    if front.get("draft") is not False or front.get("content_type") != "article":
        raise ValueError("Only explicitly published article data may be preserved")
    public_url = web_url(public_url)
    public_raw, mime, final_url = fetch(public_url, [urlsplit(public_url).hostname])
    if mime != "text/html" or front["title"] not in public_raw.decode("utf-8"):
        raise ValueError("Public URL does not expose the selected article title")
    keep = {"title", "date", "lastmod", "categories", "tags", "author", "description",
            "summary", "url", "slug", "aliases", "source_name", "source_url", "source_domain",
            "sources", "correction", "corrections", "correction_note"}
    metadata = {k: v for k, v in front.items() if k in keep or k.startswith("image")}
    record = {"public_url": public_url, "resolved_public_url": final_url,
              "source_file": str(source_file), "source_sha256": hashlib.sha256(raw).hexdigest(),
              "public_html_sha256": hashlib.sha256(public_raw).hexdigest(),
              "metadata": metadata, "body_markdown": parts[2].strip(),
              "preservation_only": True, "republication_approved": False,
              "rights_note": "Existing image/source rights fields preserved as recorded; not newly verified or upgraded."}
    target = Path(state_dir) / "history" / digest(public_url)
    target.mkdir(parents=True, exist_ok=True)
    (target / "article.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n")
    # Existing public HTML is evidence; never inserted into the new site's HTML.
    (target / "public.html").write_bytes(public_raw)
    assert hashlib.sha256(source_file.read_bytes()).hexdigest() == record["source_sha256"]
    return {"record_path": str(target / "article.json"), "public_url": public_url,
            "source_sha256": record["source_sha256"], "copied_articles": 1,
            "queue_imports": 0, "old_source_unchanged": True}
