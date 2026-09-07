#!/usr/bin/env python3
"""Offline canonical team analytics projection; never authenticates or sends.

Public mode intentionally exports availability only, never private provider data.
Team mode revalidates original private collector envelopes at consumption time.
All known output names are overwritten (blocked placeholders on bad input), with
hash manifest latest.json committed last. Consumers must verify manifest hashes.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from analytics_contract import validate_daily_report, validate_source, source_time as stamp, ctr_fraction, ga4_rows
from collect_analytics import run_report, CollectionError
from reader_retention_report import build_report
from ctr_gap_report import analyze_gsc_data

PROJECT = Path(__file__).resolve().parent.parent
WORKSPACES = ('workspace', 'workspace-alex', 'workspace-sara', 'workspace-max', 'workspace-monica', 'workspace-iris')
FORBIDDEN = ('private_key', 'client_secret', 'refresh_token', 'access_token', 'id_token',
             'authorization:', 'bearer ', 'api_key', 'apikey', 'x-api-key', 'discord.com/api/webhooks/')
MAX_INPUT_BYTES = 8 * 1024 * 1024


def read_data(path):
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES or any(s in raw.decode().lower() for s in FORBIDDEN):
            return {}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def unavailable(now, reason):
    return {'schema_version': 3, 'status': 'unavailable', 'fresh': False,
            'generated_at': now.isoformat(), 'reason': reason}


def public_status(now):
    # Explicit separation: deployment runners do not possess private collector
    # evidence. A build timestamp or old tracked validation is not provider proof.
    return dict(unavailable(now, 'private_analytics_not_exported'),
                checked_at=now.isoformat(), visibility='public',
                scope='analytics_availability_only',
                source_command='scripts/analytics_projection.py --public-output',
                artifacts={}, note='Validated analytics are available only in the private team snapshot. Public availability does not indicate provider failure.')


def safe_state(state):
    """Fixed reason codes and scalar provenance, never arbitrary exception text."""
    fresh = state.get('fresh') is True
    result = {'status': 'fresh' if fresh else 'unavailable', 'fresh': fresh,
              'reason': 'validated_source' if fresh else 'source_validation_failed'}
    for key in ('evidence_at', 'age_hours'):
        if key in state: result[key] = state[key]
    window = state.get('query_window', {})
    if fresh and window:
        result['query_window'] = {k: window[k] for k in ('startDate', 'endDate')}
    return result


def strict_ga4(source, now):
    """Replay collection-time checks offline using only captured response bytes."""
    try:
        request, response = source['request'], source['response']
        for field in ('metrics', 'dimensions'):
            names = [h['name'] for h in request.get(field, [])]
            if len(set(names)) != len(names): return False
        run_report('offline-not-sent', request, now,
                   transport=lambda *_: (source['http_status'], response))
        return validate_source(source, 'ga4', now)['fresh']
    except (CollectionError, ValueError, KeyError, TypeError, AttributeError):
        return False


def team_snapshot(project, now):
    base = project / 'analytics'
    attempt = read_data(base / 'collector-status.json')
    daily = read_data(base / 'daily-report.json')
    gsc = read_data(base / 'search-console-data.json')
    # Refuse a read spanning a collector attempt (host wrapper also serializes
    # exporter and collector). No fallback to public/static or filesystem mtime.
    stable = attempt == read_data(base / 'collector-status.json')
    ga_state = validate_daily_report(daily, now)
    sc_state = validate_source(gsc, 'gsc', now)
    components = daily.get('ga4_components', {})
    ga_originals = [daily.get('ga4_source')] + (list(components.values()) if isinstance(components, dict) else [None])
    strict_ok = all(strict_ga4(source, now) for source in ga_originals)
    returning = daily.get('ga4_returning_source')
    if not strict_ga4(returning, now):
        returning = None
    elif {r.get('newVsReturning') for r in ga4_rows(returning)} != {'new', 'returning'}:
        returning = None
    try:
        attempt_time = stamp(attempt['checked_at']).isoformat()
        coherent = all(stamp(source['fetched_at']).isoformat() == attempt_time for source in ga_originals)
        if returning is not None and stamp(returning['fetched_at']).isoformat() != attempt_time:
            returning = None
        sc_strict = (type(gsc.get('row_count')) is int
                     and all(isinstance(r.get('url'), str) and r['url'] for r in gsc['rows'])
                     and len({r['url'] for r in gsc['rows']}) == len(gsc['rows']))
    except (KeyError, ValueError, TypeError, AttributeError):
        attempt_time, coherent, sc_strict = None, False, False
    try:
        attempt_ok = (stable and coherent and attempt.get('status') == 'fresh'
                      and attempt.get('source_command') == 'pipeline/check-analytics.sh'
                      and 0 <= (now - stamp(attempt['checked_at'])).total_seconds() <= 30 * 3600
                      and stamp(attempt['checked_at']) >= stamp(ga_state['evidence_at'])
                      and stamp(attempt['checked_at']) >= stamp(sc_state['evidence_at']))
    except (ValueError, KeyError, TypeError):
        attempt_ok = False
    if not strict_ok:
        ga_state.update(status='invalid', fresh=False)
    if not sc_strict:
        sc_state.update(status='invalid', fresh=False)
    good = attempt_ok and strict_ok and sc_strict and ga_state['fresh'] and sc_state['fresh']
    reason = 'validated_private_sources' if good else 'collector_or_source_not_current'
    status = 'fresh' if good else 'blocked'
    freshness = {'schema_version': 3, 'status': status, 'fresh': good,
                 'checked_at': now.isoformat(), 'collector_checked_at': attempt_time,
                 'source_command': 'private_collector_projection', 'reason': reason,
                 'artifacts': {'daily_report': safe_state(ga_state), 'search_console': safe_state(sc_state)}}
    reader = build_report(daily.get('ga4_source'), returning, None, now)
    reader['source'] = safe_state(reader['source'])
    if reader.get('query_window'):
        reader['query_window'] = {key: reader['query_window'][key] for key in ('startDate', 'endDate')}
    if 'source' in reader['returning_active_share']:
        reader['returning_active_share']['source'] = safe_state(reader['returning_active_share']['source'])
    if 'direct_totals' in reader:
        reader['direct_totals'] = {key: value for key, value in reader['direct_totals'].items()
                                   if key in ('screenPageViews', 'activeUsers', 'totalUsers', 'sessions',
                                              'engagedSessions', 'engagementRate', 'bounceRate')}
    if reader['status'] != 'fresh':
        good = False
        freshness.update(status='blocked', fresh=False, reason='invalid_direct_goal_source')
    if not good:
        reader = dict(unavailable(now, 'source_validation_failed'), goal=None,
                      cohort_retention={'status': 'unavailable'},
                      traffic={'qa_internal_separated': False})
        daily = unavailable(now, 'source_validation_failed')
        gsc = unavailable(now, 'source_validation_failed')
        ctr = unavailable(now, 'source_validation_failed')
    else:
        # Only allowlisted aggregates leave the provider store: no original
        # response, query/page rows, arbitrary extras or unvalidated realtime.
        totals = gsc['property_totals']
        gsc_summary = {'status': 'fresh', 'query_window': safe_state(sc_state)['query_window'],
            'total_clicks': totals['clicks'], 'total_impressions': totals['impressions'],
            'avg_ctr_pct': ctr_fraction(totals) * 100, 'avg_position': totals['position'],
            'top_queries_status': 'private_not_exported'}
        daily = {'schema_version': 3, 'status': 'fresh', 'scope': 'aggregate_analytics',
                 'generated_at': ga_state['evidence_at'], 'reader_retention': reader,
                 'search_console': gsc_summary,
                 'realtime': {'status': 'unavailable', 'reason': 'not_independently_validated'}}
        gaps = analyze_gsc_data([dict(r, ctr_unit=gsc.get('ctr_unit')) for r in gsc['rows']], len(gsc['rows']))
        ctr = {'schema_version': 3, 'status': 'fresh', 'generated_at': now.isoformat(),
               'source_generated_at': sc_state['evidence_at'],
               'query_window': safe_state(sc_state)['query_window'], 'ctr_unit': 'percent',
               'data_source': 'google_search_console', 'reason': 'validated_source',
               'total_gaps_found': len(gaps), 'details_status': 'private_not_exported'}
        gsc = {'schema_version': 3, 'status': 'fresh', 'generated_at': sc_state['evidence_at'],
               'row_count': gsc['row_count'], 'summary': gsc_summary,
               'rows_status': 'private_not_exported'}
    # This is an analytics dashboard, not a fresh claim about unrelated pipeline
    # health. Retire the old exported public panel explicitly instead of blessing it.
    panel = {'schema_version': 3, 'scope': 'private_analytics_only',
             'status': freshness['status'], 'generated_at': now.isoformat(),
             'analytics': {'freshness': freshness,
                           'ga4': {'status': 'fresh' if good else 'blocked'},
                           'gsc': {'status': 'fresh' if good else 'blocked'}},
             'audience_goal': reader,
             'pipeline_status': {'status': 'unavailable', 'reason': 'consult_canonical_pipeline_status'}}
    outputs = {'analytics-freshness-status.json': freshness,
               'post-reauth-freshness-evidence.json': freshness,
               'reader-retention-report.json': reader, 'daily-report.json': daily,
               'search-console-data.json': gsc, 'ctr-gap-report.json': ctr,
               'business-control-panel.json': panel,
               'public-business-control-panel.json': unavailable(now, 'retired_stale_public_mirror')}
    # Fail closed for credential-like content anywhere in rederived output too.
    if any(s in json.dumps(outputs).lower() for s in FORBIDDEN):
        outputs = {name: unavailable(now, 'unsafe_export_content') for name in outputs}
        good = False
    summary = {'schema_version': 3, 'generated_at': now.isoformat(),
        'freshness_status': 'fresh' if good else 'blocked',
        'freshness_checked_at': now.isoformat(), 'collector_checked_at': attempt_time,
        'ga4_status': 'fresh' if good else 'blocked', 'gsc_status': 'fresh' if good else 'blocked',
        'ga4_reason': freshness['reason'], 'gsc_reason': freshness['reason'],
        'freshness_evidence_at': ga_state.get('evidence_at'),
        'search_console_generated_at': sc_state.get('evidence_at'),
        'ctr_gap_status': 'fresh' if good else 'blocked',
        'canonical_goal_report': 'reader-retention-report.json',
        'search_console_rows': gsc.get('row_count') if good else None,
        'scope': 'private_validated_collector_snapshot', 'artifacts': {}}
    return outputs, summary


def atomic_write(path, data):
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError('symlink_parent_refused')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('symlink_output_refused')
    fd, temporary = tempfile.mkstemp(prefix='.projection-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export_snapshot(outputs, summary, destinations):
    encoded = {name: (json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()
               for name, data in outputs.items()}
    encoded['README.md'] = (
        '# Private analytics snapshot — schema 3\n\n'
        'Read latest.json, then verify its artifact SHA-256 hashes before combining files. '
        'An interrupted export can leave a mixed generation: mismatched hashes mean unavailable.\n'
        'generated_at is export/check time, not provider freshness. Original evidence times '
        'are freshness_evidence_at and search_console_generated_at. Evidence expires after 30 hours.\n'
        'reader-retention-report.json contains independently rederived rolling-30 direct GA4 '
        'views/active users and the returning-user share when available. That share is NOT '
        'acquisition-cohort retention. QA/internal traffic separation and demand are unproven.\n'
        'Raw responses, query/page rows, arbitrary fields and unverified realtime are not exported. '
        'The business-control-panel.json snapshot is analytics-only; consult the canonical '
        'pipeline status for publishing health. Public availability is deliberately unavailable.\n'
        'Blocked placeholders replace old managed snapshots on validation failure; host originals '
        'are preserved. Refresh uses the existing host export-uutistenlukija-analytics-team-snapshot '
        'command without credentials, provider calls, sends or agent instruction changes.\n'
    ).encode()
    summary = copy.deepcopy(summary)
    summary['artifacts'] = {name: {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
                            for name, raw in encoded.items()}
    encoded['latest.json'] = (json.dumps(summary, indent=2) + '\n').encode()
    for dest in destinations:
        for name, raw in encoded.items():  # latest.json is the commit marker, last
            atomic_write(dest / name, raw)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output-dir', type=Path)
    group.add_argument('--team-root', type=Path)
    group.add_argument('--public-output', type=Path)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    if args.public_output:
        data = public_status(now)
        atomic_write(args.public_output, (json.dumps(data, indent=2) + '\n').encode())
        print(json.dumps({'status': data['status'], 'scope': data['scope']}))
        return 0
    destinations = [args.output_dir] if args.output_dir else [
        args.team_root / ws / 'reports/uutistenlukija-analytics' for ws in WORKSPACES
        if (args.team_root / ws).is_dir()]
    if not destinations or (args.team_root and len(destinations) != len(WORKSPACES)):
        raise ValueError('missing_expected_team_workspaces')
    outputs, summary = team_snapshot(args.project, now)
    summary = export_snapshot(outputs, summary, destinations)
    print(json.dumps({'status': summary['freshness_status'], 'destinations': len(destinations),
                      'search_console_rows': summary['search_console_rows']}))
    return 0 if summary['freshness_status'] == 'fresh' else 1


if __name__ == '__main__':
    raise SystemExit(main())
