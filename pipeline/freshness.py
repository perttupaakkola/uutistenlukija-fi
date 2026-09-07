"""Source/event freshness shared by admission and terminal publication.

Generated/queue timestamps are never evidence of a current story. Existing
packets may carry the source date in original_article.published; retain that
compatibility rather than requiring a new metadata field on every packet.
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

MAX_NEWS_AGE = timedelta(hours=96)
FUTURE_TOLERANCE = timedelta(minutes=15)
MAX_REVIEW_VALIDITY = timedelta(days=30)


def parse_source_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        if len(value.strip()) == 10:  # ISO calendar publication date, day precision
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            return None
    try:
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def freshness_reasons(value, *, now=None):
    """Return fail-closed reasons; does not modify evidence or any state.

    Editorial allowance: freshness={kind: evergreen|update, reviewed_by,
    reason, reviewed_at, valid_until, [update_at, update_source_url]}.
    An update additionally needs a recent source date and dated update evidence.
    These fields are editorial assertions to review, not semantic verification.
    """
    now = now or datetime.now(timezone.utc)
    packet = value.get('packet') if isinstance(value.get('packet'), dict) else {}
    original = value.get('original_article') if isinstance(value.get('original_article'), dict) else {}
    article = value.get('article') if isinstance(value.get('article'), dict) else value
    evidence = (packet, original, article)
    dates = []
    for obj in evidence:
        for key in ('source_published_at', 'published'):
            if key in obj:
                parsed = parse_source_date(obj[key])
                if parsed is None:
                    return ('source_date_invalid',)
                if parsed > now + FUTURE_TOLERANCE:
                    return ('source_date_future',)
                dates.append(parsed)
    if not dates:
        # Some source-current packets date the selected source block instead
        # of the original RSS row. Accept only the primary story's dated block.
        try:
            from .source_attribution import source_identity_key
        except ImportError:
            from source_attribution import source_identity_key
        selected = packet.get('selected_source') if isinstance(packet.get('selected_source'), dict) else {}
        primary_url = selected.get('url') or original.get('link') or article.get('source_url') or article.get('link')
        primary = source_identity_key(primary_url or '')
        blocks = [selected, *(packet.get('clean_source_blocks') or [])]
        for block in blocks:
            if not isinstance(block, dict) or not primary:
                continue
            if source_identity_key(block.get('source_url') or block.get('url') or '') != primary:
                continue
            for key in ('source_published_at', 'published'):
                if key not in block:
                    continue
                parsed = parse_source_date(block[key])
                if parsed is None:
                    return ('source_date_invalid',)
                if parsed > now + FUTURE_TOLERANCE:
                    return ('source_date_future',)
                dates.append(parsed)
    if not dates:
        return ('source_date_missing',)
    # Oldest declared source publication wins: generated copy cannot refresh it.
    source_at = min(dates)
    allowance = packet.get('freshness', original.get('freshness', article.get('freshness')))
    kind = ''
    if allowance is not None:
        if not isinstance(allowance, dict):
            return ('freshness_allowance_invalid',)
        reviewed = parse_source_date(allowance.get('reviewed_at'))
        expires = parse_source_date(allowance.get('valid_until'))
        kind = allowance.get('kind')
        if (kind not in ('evergreen', 'update') or not str(allowance.get('reviewed_by') or '').strip()
                or not str(allowance.get('reason') or '').strip() or reviewed is None or expires is None
                or reviewed > now or expires <= now or expires <= reviewed
                or expires - reviewed > MAX_REVIEW_VALIDITY):
            return ('freshness_allowance_invalid',)
        if kind == 'update':
            update_at = parse_source_date(allowance.get('update_at'))
            if (update_at is None or update_at > now + FUTURE_TOLERANCE
                    or now - update_at > MAX_NEWS_AGE
                    or not str(allowance.get('update_source_url') or '').startswith(('https://', 'http://'))):
                return ('freshness_update_invalid',)
    if kind != 'evergreen' and now - source_at > MAX_NEWS_AGE:
        return ('source_stale',)
    for obj in evidence:
        for key in ('event_at', 'event_date'):
            if key not in obj:
                continue
            event_at = parse_source_date(obj[key])
            if event_at is None:
                return ('event_date_invalid',)
            # Future events can be announced by a currently dated source.
            if now - event_at > MAX_NEWS_AGE and kind not in ('evergreen', 'update'):
                return ('event_stale',)
    if kind != 'evergreen' and any(obj.get('fresh_source_quota_eligible') is False or obj.get('stale_source') is True for obj in evidence):
        return ('source_policy_stale',)
    return ()
