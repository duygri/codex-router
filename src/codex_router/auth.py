"""Fail-closed adapter for the verified local Codex session profile.

The schema in this file is intentionally a synthetic compatibility profile. It
is not presented as Codex CLI's real auth schema until a public contract is
verified and a sanitized fixture is added.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class SessionStatus(Enum):
    VALID = "valid"
    EXPIRED = "expired"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


class RefreshOutcome(Enum):
    VALID = "valid"
    REFRESHED = "refreshed"
    REAUTH_REQUIRED = "reauth_required"
    UNSUPPORTED = "unsupported"


@dataclass
class Session:
    access_token: str
    expires_at: datetime


@dataclass
class LoadResult:
    status: SessionStatus
    message: str
    session: object = None
    fingerprint: str = ""


@dataclass
class RefreshResult:
    outcome: RefreshOutcome
    message: str
    session: object = None


def fingerprint_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _parse_expiry(value):
    if not isinstance(value, str):
        raise ValueError("expires_at must be an ISO-8601 string")
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class AuthAdapter:
    """Reads one explicitly verified session profile and never writes it."""

    def __init__(self, path, refresh_callback=None, adapter_version="synthetic-v1"):
        self.path = os.fspath(path)
        self.refresh_callback = refresh_callback
        self.adapter_version = adapter_version

    def detect(self):
        if not os.path.isfile(self.path):
            return LoadResult(SessionStatus.MISSING, "Codex session file was not found")
        return LoadResult(SessionStatus.VALID, "Codex session file detected")

    def _read_stable(self):
        for _ in range(2):
            try:
                with open(self.path, "rb") as stream:
                    before_data = stream.read()
                before = fingerprint_bytes(before_data)
                with open(self.path, "rb") as stream:
                    data = stream.read()
                after = fingerprint_bytes(data)
            except (OSError, IOError) as exc:
                return None, "Unable to read Codex session file: %s" % type(exc).__name__
            if before == after:
                return data, after
        return None, "Codex session changed while it was being read"

    def load_session(self):
        if not os.path.isfile(self.path):
            return LoadResult(SessionStatus.MISSING, "Codex session file was not found")

        data, fingerprint_or_error = self._read_stable()
        if data is None:
            return LoadResult(SessionStatus.UNSUPPORTED, fingerprint_or_error)
        fingerprint = fingerprint_or_error

        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return LoadResult(SessionStatus.UNSUPPORTED, "Codex session is not valid JSON", fingerprint=fingerprint)

        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return LoadResult(SessionStatus.UNSUPPORTED, "Codex session schema is not verified", fingerprint=fingerprint)

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            return LoadResult(SessionStatus.UNSUPPORTED, "Codex session has no verified access token", fingerprint=fingerprint)

        try:
            expires_at = _parse_expiry(payload.get("expires_at"))
        except (TypeError, ValueError):
            return LoadResult(SessionStatus.UNSUPPORTED, "Codex session expiry is invalid", fingerprint=fingerprint)

        session = Session(token, expires_at)
        if expires_at <= datetime.now(timezone.utc):
            return LoadResult(SessionStatus.EXPIRED, "Codex session has expired", session, fingerprint)
        return LoadResult(SessionStatus.VALID, "Codex session is valid", session, fingerprint)

    def refresh_if_needed(self, result):
        if result.status == SessionStatus.VALID:
            return RefreshResult(RefreshOutcome.VALID, "Codex session is valid", result.session)
        if result.status != SessionStatus.EXPIRED:
            return RefreshResult(RefreshOutcome.UNSUPPORTED, "Codex session cannot be refreshed safely")
        if self.refresh_callback is None:
            return RefreshResult(RefreshOutcome.REAUTH_REQUIRED, "Run codex login to reauthenticate")
        try:
            refreshed_session = self.refresh_callback(result.session)
        except Exception:
            return RefreshResult(RefreshOutcome.UNSUPPORTED, "Codex refresh contract failed")
        if not isinstance(refreshed_session, Session):
            return RefreshResult(RefreshOutcome.UNSUPPORTED, "Codex refresh contract returned an invalid session")
        return RefreshResult(RefreshOutcome.REFRESHED, "Codex session was refreshed", refreshed_session)

    def health_check(self):
        return self.load_session()
