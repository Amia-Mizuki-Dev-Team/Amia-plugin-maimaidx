"""Shared, non-secret Diving-Fish OAuth binding metadata.

The existing ``maimai_sync.user_binds.fish_token`` column is an Import-Token
used by the upload plugin and must not be repurposed for OAuth.  This module
defines the small JSON contract stored in the separate ``diving_fish_oauth``
column.  It contains enough information for another plugin to recognise the
same consent, while short-lived access tokens and application secrets remain
process-only.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from typing import Any


OAUTH_BINDING_KEY = "diving_fish_oauth"
OAUTH_BINDING_VERSION = 1
OAUTH_PROVIDER = "diving-fish"
OAUTH_READ_SCOPE = "prober.records.read"
_SUBJECT_RE = re.compile(r"^ref:[0-9a-f]{64}$")


def _scopes(value: object) -> list[str] | None:
    """Mirror the strict shared Sync contract for stored marker values."""

    if not isinstance(value, (list, tuple)):
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        scope = item.strip()
        if not scope:
            return None
        if scope not in result:
            result.append(scope)
    return result


def build_oauth_binding(
    oauth: object,
    external_id: str,
    *,
    now: int | float | None = None,
) -> dict[str, Any]:
    """Build the durable consent marker for one qbind-resolved identity."""

    client_id = str(getattr(oauth, "client_id", "") or "").strip()
    subject_ref = str(oauth.subject_ref(str(external_id))).strip()
    if not client_id or not _SUBJECT_RE.fullmatch(subject_ref):
        raise ValueError("invalid Diving-Fish OAuth subject")
    raw_scope = getattr(oauth, "scope", "")
    if isinstance(raw_scope, str):
        raw_scope = raw_scope.split()
    scopes = _scopes(raw_scope)
    if scopes is None:
        raise ValueError("invalid OAuth binding scope")
    timestamp = int(time.time() if now is None else now)
    if timestamp <= 0:
        raise ValueError("invalid OAuth binding timestamp")
    return {
        "version": OAUTH_BINDING_VERSION,
        "provider": OAUTH_PROVIDER,
        "status": "authorized",
        "client_id": client_id,
        "subject_ref": subject_ref,
        "scope": scopes,
        "authorized_at": timestamp,
        "checked_at": timestamp,
    }


def normalize_oauth_binding(value: object) -> dict[str, Any] | None:
    """Parse and allowlist a stored binding without returning secret fields."""

    candidate: object = value
    if isinstance(value, str):
        try:
            candidate = json.loads(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(candidate, Mapping):
        return None
    version = candidate.get("version")
    authorized_at = candidate.get("authorized_at")
    checked_at = candidate.get("checked_at")
    provider = candidate.get("provider")
    status = candidate.get("status")
    client_id = candidate.get("client_id")
    subject_ref = candidate.get("subject_ref")
    scopes = _scopes(candidate.get("scope"))
    if any(
        type(item) is not int
        for item in (version, authorized_at, checked_at)
    ):
        return None
    if (
        version != OAUTH_BINDING_VERSION
        or provider != OAUTH_PROVIDER
        or status != "authorized"
        or not isinstance(client_id, str)
        or not client_id.strip()
        or not isinstance(subject_ref, str)
        or not _SUBJECT_RE.fullmatch(subject_ref.strip())
        or scopes is None
        or authorized_at <= 0
        or checked_at <= 0
    ):
        return None
    # Deliberately construct a new allowlisted object.  Even if an old row
    # contains access_token/device_code fields, callers never receive them.
    return {
        "version": version,
        "provider": provider,
        "status": status,
        "client_id": client_id.strip(),
        "subject_ref": subject_ref.strip(),
        "scope": scopes,
        "authorized_at": authorized_at,
        "checked_at": checked_at,
    }


def is_authorized_oauth_binding(value: object) -> bool:
    """Return whether a stored marker grants the read scope we need."""

    normalized = normalize_oauth_binding(value)
    return bool(normalized and OAUTH_READ_SCOPE in normalized["scope"])
