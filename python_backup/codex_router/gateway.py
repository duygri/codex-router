"""OpenAI-compatible upstream transport with fail-closed auth handling."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .auth import RefreshOutcome, SessionStatus


class GatewayError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class Gateway:
    def __init__(self, auth_adapter, upstream_url, opener=None, timeout=30):
        self.auth_adapter = auth_adapter
        self.upstream_url = (upstream_url or "").rstrip("/")
        self.opener = opener or urlopen
        self.timeout = timeout

    def _authenticate(self):
        loaded = self.auth_adapter.load_session()
        refreshed = self.auth_adapter.refresh_if_needed(loaded)
        if refreshed.outcome in (RefreshOutcome.VALID, RefreshOutcome.REFRESHED):
            return refreshed.session, loaded.fingerprint
        if loaded.status == SessionStatus.MISSING:
            raise GatewayError(401, "auth_required", "Run codex login before using the router")
        if refreshed.outcome == RefreshOutcome.REAUTH_REQUIRED or loaded.status == SessionStatus.EXPIRED:
            raise GatewayError(401, "auth_expired", "Run codex login to reauthenticate")
        raise GatewayError(503, "unsupported_codex_version", "Codex authentication format is not supported")

    def ensure_session_current(self, fingerprint):
        if not fingerprint or self.auth_adapter.current_fingerprint() != fingerprint:
            raise GatewayError(401, "auth_expired", "Codex session changed; reauthenticate and retry")

    def open_upstream(self, method, path, payload=None):
        if not self.upstream_url:
            raise GatewayError(503, "upstream_not_configured", "Set CODEX_ROUTER_UPSTREAM_URL before sending requests")
        session, fingerprint = self._authenticate()
        self.ensure_session_current(fingerprint)

        data = None if payload is None else json.dumps(payload).encode("utf-8")
        url = self.upstream_url + (path if path.startswith("/") else "/" + path)
        request = Request(url, data=data, method=method.upper())
        request.add_header("Authorization", "Bearer " + session.access_token)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")

        try:
            return self.opener(request, timeout=self.timeout)
        except HTTPError as exc:
            raise GatewayError(exc.code, "upstream_error", "Upstream returned an HTTP error")
        except URLError:
            raise GatewayError(502, "upstream_unavailable", "Upstream could not be reached")
