#!/usr/bin/env python3
"""Private daily analytics producer, invoked by pipeline/check-analytics.sh.

--output-dir isolates ALL artifacts; --gsc-input reuses a validated v2 export.
--dry-run/--no-write performs bounded read-only provider queries but writes nothing
(including tokens). It is not an offline mode. No sends or public static output.
GA4 goal totals and returning breakdown are independent completed Helsinki windows.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from analytics_contract import GA4_PROPERTY, GSC_PROPERTY, ctr_fraction, ga4_rows, number, validate_source, validate_daily_report
from fetch_search_console import fetch_report
from google_access_token import service_account_access_token
from reader_retention_report import build_report

PROJECT_DIR = Path(__file__).resolve().parent.parent
GA4_ENDPOINT = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY}:runReport"
GSC_ENDPOINT = ("https://searchconsole.googleapis.com/webmasters/v3/sites/"
                + urllib.parse.quote(GSC_PROPERTY, safe="") + "/searchAnalytics/query")
MAX_BYTES = 4 * 1024 * 1024
METRICS = ["screenPageViews", "activeUsers", "sessions", "engagementRate", "bounceRate"]


class CollectionError(Exception):
    """Only fixed reason codes, never provider messages or authentication material."""


def post_json(endpoint, payload, token):
    req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), method="POST",
          headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "User-Agent": "Uutistenlukija-Analytics/2"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status = response.status
            raw = response.read(MAX_BYTES + 1)
        if status != 200:
            raise CollectionError("http_error")
        if len(raw) > MAX_BYTES:
            raise CollectionError("response_size_limit")
        result = json.loads(raw)
        if not isinstance(result, dict) or "error" in result:
            raise CollectionError("provider_error")
        return status, result
    except urllib.error.HTTPError as exc:
        raise CollectionError(f"http_{exc.code}") from None
    except (OSError, ValueError):
        raise CollectionError("transport_or_json_error") from None


def get_token(service):
    """Existing scoped SA helper, then existing OAuth format; refresh in memory only."""
    scope = "analytics.readonly" if service == "ga4" else "webmasters.readonly"
    try:
        result = service_account_access_token([f"https://www.googleapis.com/auth/{scope}"])
        if result:
            return result[0]
        name = "analytics-tokens.json" if service == "ga4" else "search-console-tokens.json"
        override = os.environ.get("SECRETS_DIR")
        directories = [Path(override)] if override else [
            Path.home() / ".openclaw/workspace/.secrets", Path("/workspace/.secrets"),
            PROJECT_DIR / ".secrets"]
        path = next((p / name for p in directories if (p / name).is_file()), None)
        if path is None:
            raise CollectionError("auth_unavailable")
        creds = json.loads(path.read_text())
        form = {key: creds[key] for key in ("client_id", "client_secret", "refresh_token")}
        form["grant_type"] = "refresh_token"
        request = urllib.request.Request("https://oauth2.googleapis.com/token",
                  data=urllib.parse.urlencode(form).encode(), method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                raise CollectionError("auth_failed")
            token = json.loads(raw).get("access_token")
        if not isinstance(token, str) or not token:
            raise CollectionError("auth_failed")
        return token
    except Exception:
        raise CollectionError("auth_failed") from None


def window(now, days):
    end = now.astimezone(ZoneInfo("Europe/Helsinki")).date() - timedelta(days=1)
    return {"startDate": (end - timedelta(days=days - 1)).isoformat(), "endDate": end.isoformat()}


def request_for(now, days, metrics, dimensions=(), limit=10000):
    request = {"dateRanges": [window(now, days)], "metrics": [{"name": m} for m in metrics],
               "limit": limit}
    if dimensions:
        request["dimensions"] = [{"name": d} for d in dimensions]
    return request


def run_report(token, request, now, transport=post_json):
    status, response = transport(GA4_ENDPOINT, copy.deepcopy(request), token)
    envelope = {"fetched_at": now.isoformat(), "http_status": status,
                "endpoint": GA4_ENDPOINT, "request": copy.deepcopy(request), "response": response}
    # Reject even a partial success object with an error alongside rows.
    if not isinstance(response, dict) or "error" in response:
        raise CollectionError("provider_error")
    if type(response.get("rowCount")) is not int:
        raise CollectionError("invalid_row_count")
    state = validate_source(envelope, "ga4", now)
    if not state["fresh"]:
        raise CollectionError("invalid_ga4_source")
    if response.get("metadata", {}).get("timeZone") != "Europe/Helsinki":
        raise CollectionError("wrong_property_timezone")
    rows = ga4_rows(envelope)
    dimensions = [d["name"] for d in request.get("dimensions", [])]
    if len({tuple(r[d] for d in dimensions) for r in rows}) != len(rows):
        raise CollectionError("duplicate_dimension_rows")
    for row in rows:
        for metric in ("engagementRate", "bounceRate"):
            if row.get(metric, 0) > 1:
                raise CollectionError("invalid_rate")
    return envelope


def collect(now, token_fn=get_token, transport=post_json, gsc_input=None):
    token = token_fn("ga4")
    totals = run_report(token, request_for(now, 30, METRICS), now, transport)
    returning = run_report(token, request_for(now, 30, ["activeUsers"], ["newVsReturning"]), now, transport)
    daily = run_report(token, request_for(now, 2, ["screenPageViews", "sessions", "totalUsers"], ["date"]), now, transport)
    pages = run_report(token, request_for(now, 7, ["screenPageViews"], ["pagePath", "pageTitle"]), now, transport)
    sources = run_report(token, request_for(now, 7, ["sessions"], ["sessionSource", "sessionMedium"]), now, transport)
    realtime_request = {"metrics": [{"name": "activeUsers"}]}
    rt_status, realtime = transport(GA4_ENDPOINT.replace(":runReport", ":runRealtimeReport"), realtime_request, token)
    if rt_status != 200 or not isinstance(realtime, dict) or "error" in realtime:
        raise CollectionError("realtime_provider_error")
    rt_rows = realtime.get("rows", [])
    rt_projection = {"active_users": None, "status": "unavailable", "reason": "empty_realtime_report"}
    if rt_rows:
        if (realtime.get("metricHeaders") != [{"name": "activeUsers", "type": "TYPE_INTEGER"}]
                or len(rt_rows) != 1 or realtime.get("rowCount") != 1
                or realtime.get("dimensionHeaders") or len(rt_rows[0]["metricValues"]) != 1):
            raise CollectionError("invalid_realtime_schema")
        rt_projection = {"active_users": number(rt_rows[0]["metricValues"][0]["value"]), "status": "fresh"}
    queries = []
    if gsc_input is None:
        sc_token = token_fn("gsc")
        def query(_token, payload):
            status, response = transport(GSC_ENDPOINT, payload, sc_token)
            if status != 200 or not isinstance(response, dict) or "error" in response:
                raise CollectionError("gsc_provider_error")
            return response
        # Existing v2 envelope and byProperty totals, at most four page requests + totals.
        gsc = fetch_report(sc_token, now=now, query_fn=query)
        query_response = query(sc_token, dict(gsc["query_window"], type="web", dataState="final",
                                             dimensions=["query"], rowLimit=10, startRow=0))
        if not isinstance(query_response.get("rows", []), list) or len(query_response.get("rows", [])) > 10:
            raise CollectionError("invalid_gsc_queries")
        for row in query_response.get("rows", []):
            if len(row["keys"]) != 1 or not isinstance(row["keys"][0], str):
                raise CollectionError("invalid_gsc_query")
            queries.append({"query": row["keys"][0], "clicks": number(row["clicks"]),
                            "impressions": number(row["impressions"]),
                            "ctr_pct": round(ctr_fraction(row) * 100, 2),
                            "position": round(number(row["position"]), 1)})
    else:
        gsc = json.loads(Path(gsc_input).read_text())
    if not validate_source(gsc, "gsc", now)["fresh"]:
        raise CollectionError("invalid_gsc_source")
    reader = build_report(totals, returning, gsc, now)
    if reader["status"] != "fresh":
        raise CollectionError("invalid_reader_report")
    sc_totals = gsc["property_totals"]
    report = {"schema_version": 2, "generated_at": now.isoformat(), "status": "fresh",
              "property_id": GA4_PROPERTY, "site": GSC_PROPERTY, "ga4_source": totals,
              "ga4_returning_source": returning, "reader_retention": reader,
              "ga4_components": {"daily_pageviews": daily, "top_pages_7d": pages,
                                 "traffic_sources_7d": sources},
              "query_windows": {"daily_pageviews": window(now, 2), "top_pages_7d": window(now, 7),
                                "traffic_sources_7d": window(now, 7)},
              "realtime": rt_projection,
              "daily_pageviews": sorted(ga4_rows(daily), key=lambda r: r["date"], reverse=True),
              "top_pages_7d": [{"path": r["pagePath"], "title": r["pageTitle"], "pageviews": r["screenPageViews"]}
                               for r in sorted(ga4_rows(pages), key=lambda r: -r["screenPageViews"])[:10]],
              "traffic_sources_7d": [{"source": r["sessionSource"], "medium": r["sessionMedium"], "sessions": r["sessions"]}
                                     for r in sorted(ga4_rows(sources), key=lambda r: -r["sessions"])[:10]],
              "search_console": {"status": "fresh", "period": f"{gsc['days']}d", "query_window": gsc["query_window"],
                  "total_clicks": sc_totals["clicks"], "total_impressions": sc_totals["impressions"],
                  "avg_ctr_pct": round(sc_totals["ctr_fraction"] * 100, 2), "avg_position": round(sc_totals["position"], 1),
                  "top_queries": queries, "top_queries_status": "available" if gsc_input is None else "unavailable_in_page_export"}}
    if not validate_daily_report(report, now)["fresh"]:
        raise CollectionError("invalid_daily_components")
    return {"daily-report.json": report, "ga4-rolling30.json": totals,
            "ga4-returning30.json": returning, "reader-retention-report.json": reader,
            "search-console-data.json": gsc}


def atomic_bytes(path, content):
    """Per-file atomic replace, mode 0600. Never expose incomplete JSON."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".analytics-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def publish(output_dir, artifacts):
    # Serialize all artifacts before mutation; restore original bytes on a handled
    # write failure. Daily-report contains its own canonical reader/source snapshot
    # and is replaced last. This is not a multi-file transaction across power loss.
    serialized = {name: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
                  for name, value in artifacts.items()}
    previous = {name: (output_dir / name).read_bytes() if (output_dir / name).exists() else None
                for name in artifacts}
    changed = []
    try:
        for name in sorted(artifacts, key=lambda n: n == "daily-report.json"):
            atomic_bytes(output_dir / name, serialized[name])
            changed.append(name)
    except OSError:
        for name in reversed(changed):
            if previous[name] is None:
                (output_dir / name).unlink()
            else:
                atomic_bytes(output_dir / name, previous[name])
        raise


def freshness(artifacts, now, output_dir, status, reason):
    summaries = {}
    for key, filename, kind in (("daily_report", "ga4-rolling30.json", "ga4"),
                                ("search_console", "search-console-data.json", "gsc")):
        state = (validate_daily_report(artifacts.get("daily-report.json"), now)
                 if key == "daily_report" else validate_source(artifacts.get(filename), kind, now))
        # A failed attempt cannot acquire freshness from preserved files.
        state.update(artifact=str(output_dir / ("daily-report.json" if key == "daily_report" else filename)))
        if key == "daily_report":
            state.update(property_id=GA4_PROPERTY, site=GSC_PROPERTY)
        summaries[key] = state
    summaries["oauth_blocker"] = {"blocked": reason == "auth_failed", "services": []}
    from analytics_contract import canonical_source_hash
    digests = {name: canonical_source_hash(artifacts.get(name))
               for name in ("daily-report.json", "search-console-data.json")} if status == "fresh" else {}
    return {"status": status, "checked_at": now.isoformat(), "max_age_hours": 30,
            "source_sha256": digests,
            "source_command": "pipeline/check-analytics.sh", "reason": reason,
            "artifacts": summaries, "last_good_preserved": status != "fresh"}


def execute(output_dir, *, no_write=False, gsc_input=None, now=None, token_fn=get_token, transport=post_json):
    now = now or datetime.now(timezone.utc)
    artifacts = {}
    reason = "validated_source"
    try:
        artifacts = collect(now, token_fn, transport, gsc_input)
        status = "fresh"
    except CollectionError as exc:
        status, reason = "blocked", str(exc)
    except Exception:
        status, reason = "blocked", "collection_failed"
    evidence = freshness(artifacts, now, output_dir, status, reason)
    if status == "fresh" and any(value is None for value in evidence["source_sha256"].values()):
        artifacts, status, reason = {}, "blocked", "invalid_source_serialization"
        evidence = freshness(artifacts, now, output_dir, status, reason)
    if not no_write:
        try:
            # Collect and validate EVERYTHING before touching last-good reports.
            # Daily report is the compatibility commit marker, published last.
            publish(output_dir, artifacts)
        except OSError:
            status, reason = "blocked", "output_write_failed"
            evidence = freshness({}, now, output_dir, status, reason)
            evidence["last_good_preserved"] = None  # rollback can itself fail on a broken filesystem
        atomic_json(output_dir / "collector-status.json", evidence)
        atomic_json(output_dir / "post-reauth-freshness-evidence.json", evidence)
    return (0 if status == "fresh" else 1), evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "analytics")
    parser.add_argument("--gsc-input", type=Path, help="Existing validated v2 GSC export; skips GSC authentication/queries")
    parser.add_argument("--dry-run", "--no-write", dest="no_write", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_summary", help="Print redacted evidence (always emitted)")
    args = parser.parse_args(argv)
    try:
        code, evidence = execute(args.output_dir.expanduser().resolve(), no_write=args.no_write,
                                 gsc_input=args.gsc_input)
    except OSError:
        code, evidence = 1, {"status": "blocked", "reason": "output_write_failed", "last_good_preserved": None}
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
