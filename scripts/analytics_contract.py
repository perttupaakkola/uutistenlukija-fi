"""Analytics units and source validation. Pure helpers; no provider or file access.

CTR is a fraction internally. Legacy exported `ctr` stays percent; clicks /
impressions takes precedence, including zero. Ambiguous CTR-only rows fail closed.
"""
import math
from datetime import date, datetime, timezone

GA4_PROPERTY = "529369568"
GSC_PROPERTY = "sc-domain:uutistenlukija.fi"


def number(value):
    if isinstance(value, bool):
        raise ValueError("boolean metric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("invalid metric")
    return result


def ctr_fraction(row, unit=None):
    if row.get("clicks") is not None and row.get("impressions") is not None:
        clicks, impressions = number(row["clicks"]), number(row["impressions"])
        if clicks > impressions:
            raise ValueError("clicks exceed impressions")
        return clicks / impressions if impressions else 0.0
    if row.get("ctr_fraction") is not None:
        value = number(row["ctr_fraction"])
    else:
        unit = row.get("ctr_unit", unit)
        if unit not in ("percent", "fraction") or row.get("ctr") is None:
            raise ValueError("missing or ambiguous CTR unit")
        value = number(row["ctr"]) / (100 if unit == "percent" else 1)
    if value > 1:
        raise ValueError("CTR outside [0,1]")
    return value


def source_time(value):
    if not isinstance(value, str):
        raise ValueError("missing source timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("source timestamp requires timezone")
    return result.astimezone(timezone.utc)


def validate_source(data, kind, now=None, max_age_hours=30, expected_days=None):
    """Return explicit state. File modification time never establishes freshness."""
    now = now or datetime.now(timezone.utc)
    result = {"status": "invalid", "fresh": False, "reason": "invalid_schema"}
    try:
        if not isinstance(data, dict) or not data:
            raise ValueError("empty_or_invalid_schema")
        generated = source_time(data.get("fetched_at", data.get("generated_at")))
        age = (now - generated).total_seconds() / 3600
        result.update(evidence_at=generated.isoformat(), age_hours=round(age, 2))
        if age < -0.0834:
            raise ValueError("future_source_timestamp")
        if age > max_age_hours:
            result.update(status="stale", reason="source_timestamp_stale")
            return result
        if kind == "gsc":
            if data.get("schema_version") != 2 or data.get("site") != GSC_PROPERTY:
                raise ValueError("schema_or_property_mismatch")
            if data.get("ctr_unit") != "percent" or data.get("canonical_ctr_field") != "ctr_fraction":
                raise ValueError("missing_ctr_schema")
            if data.get("search_type") != "web" or data.get("data_state") != "final":
                raise ValueError("wrong_search_type_or_data_state")
            window = data["query_window"]
            rows = data["rows"]
            if not rows or data.get("row_count") != len(rows):
                raise ValueError("empty_or_invalid_rows")
            for row in rows:
                for metric in ("clicks", "impressions", "position"):
                    number(row[metric])
                ctr_fraction(row, data.get("ctr_unit"))
                if not row.get("url"):
                    raise ValueError("missing_page")
            if data.get("completeness", {}).get("pagination_exhausted") is not True:
                raise ValueError("incomplete_pagination")
            totals = data["property_totals"]
            for metric in ("clicks", "impressions", "position"):
                number(totals[metric])
            ctr_fraction(totals)
            if totals.get("aggregation_type") != "byProperty":
                raise ValueError("invalid_property_totals")
        elif kind == "ga4":
            endpoint = "https://analyticsdata.googleapis.com/v1beta/properties/" + GA4_PROPERTY + ":runReport"
            if data.get("endpoint") != endpoint or data.get("http_status") != 200:
                raise ValueError("property_or_provider_failure")
            request, response = data["request"], data["response"]
            if len(request["dateRanges"]) != 1:
                raise ValueError("ambiguous_window")
            window = request["dateRanges"][0]
            rows = response["rows"]
            headers = response["metricHeaders"]
            if not rows or len(rows) != response["rowCount"] or not headers:
                raise ValueError("empty_or_incomplete_rows")
            metadata = response.get("metadata", {})
            if metadata.get("subjectToThresholding") or metadata.get("dataLossFromOtherRow") or metadata.get("samplingMetadatas"):
                raise ValueError("limited_provider_data")
            if [h["name"] for h in headers] != [h["name"] for h in request["metrics"]]:
                raise ValueError("metric_schema_mismatch")
            dimensions = [h["name"] for h in request.get("dimensions", [])]
            if dimensions != [h["name"] for h in response.get("dimensionHeaders", [])]:
                raise ValueError("dimension_schema_mismatch")
            for row in rows:
                if len(row["metricValues"]) != len(headers) or len(row.get("dimensionValues", [])) != len(dimensions):
                    raise ValueError("row_schema_mismatch")
                for metric in row["metricValues"]:
                    number(metric["value"])
        else:
            raise ValueError("unsupported_schema_missing_query_window")
        start, end = date.fromisoformat(window["startDate"]), date.fromisoformat(window["endDate"])
        days = (end - start).days + 1
        if days < 1 or (expected_days is not None and days != expected_days) or (kind == "gsc" and days != data.get("days")):
            raise ValueError("wrong_query_window")
        # GA4 property uses Helsinki days; GSC final data can lag by three days.
        from zoneinfo import ZoneInfo
        today = now.astimezone(ZoneInfo("Europe/Helsinki") if kind == "ga4" else timezone.utc).date()
        lag = (today - end).days
        if lag < 1 or lag > (3 if kind == "gsc" else 2) or end > generated.date():
            raise ValueError("query_window_stale_or_incomplete")
        result.update(status="fresh", fresh=True, reason="validated_source", query_window=window)
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
        result["reason"] = str(exc)
    return result


def ga4_rows(data):
    response = data["response"]
    dims = [h["name"] for h in response.get("dimensionHeaders", [])]
    metrics = [h["name"] for h in response["metricHeaders"]]
    return [dict(zip(dims, [v["value"] for v in row.get("dimensionValues", [])]),
                 **dict(zip(metrics, [number(v["value"]) for v in row["metricValues"]])))
            for row in response["rows"]]


def validate_daily_report(data, now=None, max_age_hours=30):
    """Validate every GA4 component, not merely a successful embedded total."""
    if not isinstance(data, dict) or "ga4_source" not in data:
        return validate_source(data, "ga4", now, max_age_hours)
    result = validate_source(data.get("ga4_source"), "ga4", now, max_age_hours, expected_days=30)
    if not result["fresh"]:
        return result
    specs = {
        "daily_pageviews": (2, ["date"], ["screenPageViews", "sessions", "totalUsers"]),
        "top_pages_7d": (7, ["pagePath", "pageTitle"], ["screenPageViews"]),
        "traffic_sources_7d": (7, ["sessionSource", "sessionMedium"], ["sessions"]),
    }
    try:
        if data.get("schema_version") != 2 or data.get("status") != "fresh":
            raise ValueError("invalid_daily_schema_or_status")
        end = result["query_window"]["endDate"]
        for name, (days, dimensions, metrics) in specs.items():
            source = data.get("ga4_components", {}).get(name)
            state = validate_source(source, "ga4", now, max_age_hours, expected_days=days)
            if not state["fresh"]:
                raise ValueError("invalid_component:" + name)
            request = source["request"]
            if ([d["name"] for d in request.get("dimensions", [])] != dimensions
                    or [m["name"] for m in request["metrics"]] != metrics
                    or request.get("dimensionFilter") or request.get("metricFilter")
                    or state["query_window"]["endDate"] != end
                    or data.get("query_windows", {}).get(name) != state["query_window"]):
                raise ValueError("wrong_component_scope:" + name)
            rows = ga4_rows(source)
            if name == "daily_pageviews":
                projected = sorted(rows, key=lambda r: r["date"], reverse=True)
            elif name == "top_pages_7d":
                projected = [{"path": r["pagePath"], "title": r["pageTitle"], "pageviews": r["screenPageViews"]}
                             for r in sorted(rows, key=lambda r: -r["screenPageViews"])[:10]]
            else:
                projected = [{"source": r["sessionSource"], "medium": r["sessionMedium"], "sessions": r["sessions"]}
                             for r in sorted(rows, key=lambda r: -r["sessions"])[:10]]
            if data.get(name) != projected:
                raise ValueError("component_projection_mismatch:" + name)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        result.update(status="invalid", fresh=False, reason=str(exc))
    return result


def traffic_classification(parameters):
    """Only explicit labels classify QA/internal; unknown traffic is not bots."""
    value = parameters.get("traffic_type")
    return value if value in ("qa", "internal") else "unclassified"
