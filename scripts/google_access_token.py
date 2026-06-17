#!/usr/bin/env python3
"""Google access-token helpers for uutistenlukija.fi analytics scripts.

Prefer a service account when one is available so GA4/Search Console jobs do not
rely on short-lived OAuth Testing refresh tokens. Falls back cleanly when no
service-account JSON is present.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

SERVICE_ACCOUNT_FILENAMES = (
    "uutistenlukija-google-service-account.json",
    "google-service-account.json",
    "analytics-service-account.json",
)

SERVICE_ACCOUNT_DIRS = (
    Path("/home/pertt/.openclaw/workspace/.secrets"),
    Path("/workspace/.secrets"),
    Path(__file__).resolve().parent.parent / ".secrets",
)

ENABLE_MARKERS = (
    Path("/home/pertt/.openclaw/workspace/.secrets/uutistenlukija-google-service-account.enabled"),
    Path("/workspace/.secrets/uutistenlukija-google-service-account.enabled"),
    Path(__file__).resolve().parent.parent / ".secrets" / "uutistenlukija-google-service-account.enabled",
)


def service_account_enabled() -> bool:
    override = os.environ.get("UUTISTENLUKIJA_USE_SERVICE_ACCOUNT", "").strip().lower()
    if override in {"1", "true", "yes", "on"}:
        return True
    if override in {"0", "false", "no", "off"}:
        return False
    return any(marker.exists() for marker in ENABLE_MARKERS)


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("UUTISTENLUKIJA_GOOGLE_SERVICE_ACCOUNT", "GOOGLE_APPLICATION_CREDENTIALS"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value).expanduser())
    for directory in SERVICE_ACCOUNT_DIRS:
        for filename in SERVICE_ACCOUNT_FILENAMES:
            candidates.append(directory / filename)
    return candidates


def find_service_account_file() -> Path | None:
    for path in _candidate_paths():
        if not path.exists() or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        if payload.get("type") == "service_account" and payload.get("client_email") and payload.get("private_key"):
            return path
    return None


def service_account_identity(path: Path) -> str:
    try:
        payload = json.loads(path.read_text())
        return str(payload.get("client_email") or path.name)
    except Exception:
        return path.name


def service_account_access_token(scopes: Iterable[str]) -> tuple[str, Path, str] | None:
    """Return (access_token, credential_path, client_email) or None.

    The token itself is short-lived and must never be logged. The client_email is
    not a secret and is useful as the account to grant access in GA4/GSC.
    Service-account use is gated by an enable marker so simply uploading a key
    does not break the current OAuth fallback before GA4/GSC permissions exist.
    """
    if not service_account_enabled():
        return None
    credential_path = find_service_account_file()
    if credential_path is None:
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            str(credential_path),
            scopes=list(scopes),
        )
        credentials.refresh(Request())
        if not credentials.token:
            return None
        return credentials.token, credential_path, service_account_identity(credential_path)
    except Exception as exc:  # noqa: BLE001 - callers handle fallback/logging context
        raise RuntimeError(f"service account token refresh failed: {type(exc).__name__}: {exc}") from exc
