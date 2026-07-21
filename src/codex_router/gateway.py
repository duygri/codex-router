"""OpenAI-compatible upstream transport with fail-closed auth handling."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .auth import RefreshOutcome, SessionStatus
from .app_server import AppServerBridge, AppServerError, _MemoryResponse


class GatewayError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise GatewayError(502, "upstream_redirect_blocked", "Upstream redirects are disabled")


def _is_loopback(hostname):
    return (hostname or "").lower().rstrip(".") in ("127.0.0.1", "localhost", "::1")


def _validate_upstream_url(value):
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise GatewayError(503, "unsafe_upstream", "Configured upstream URL is invalid")
    if parsed.username or parsed.password or parsed.fragment or parsed.query or not parsed.hostname:
        raise GatewayError(503, "unsafe_upstream", "Configured upstream URL is unsafe")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "api.openai.com":
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise GatewayError(503, "unsafe_upstream", "OpenAI upstream must use HTTPS")
        return
    if _is_loopback(hostname):
        if parsed.scheme not in ("http", "https"):
            raise GatewayError(503, "unsafe_upstream", "Loopback upstream scheme is invalid")
        return
    if parsed.scheme == "http":
        raise GatewayError(503, "insecure_upstream", "Non-loopback upstream must use HTTPS")
    raise GatewayError(503, "unsafe_upstream", "Remote custom upstreams are disabled")


class Gateway:
    def __init__(self, auth_adapter, upstream_url, opener=None, timeout=30, app_server=None, app_server_command="codex"):
        self.auth_adapter = auth_adapter
        self.upstream_url = (upstream_url or "").rstrip("/")
        self.opener = opener or build_opener(_NoRedirectHandler())
        self.timeout = timeout
        self.app_server = app_server or (
            AppServerBridge(command=app_server_command, timeout=timeout)
            if getattr(auth_adapter, "adapter_version", "") == "real-v1"
            else None
        )

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
        if getattr(self.auth_adapter, "adapter_version", "") == "real-v1":
            raise GatewayError(501, "direct_bearer_disabled", "real-v1 uses Codex App Server instead of direct bearer forwarding")
        if not self.upstream_url:
            raise GatewayError(503, "upstream_not_configured", "Set CODEX_ROUTER_UPSTREAM_URL before sending requests")
        _validate_upstream_url(self.upstream_url)
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
            if hasattr(self.opener, "open"):
                return self.opener.open(request, timeout=self.timeout)
            return self.opener(request, timeout=self.timeout)
        except GatewayError:
            raise
        except HTTPError as exc:
            if exc.code == 401:
                raise GatewayError(401, "auth_expired", "Codex access token was rejected; run codex login")
            raise GatewayError(exc.code, "upstream_error", "Upstream returned an HTTP error")
        except URLError:
            raise GatewayError(502, "upstream_unavailable", "Upstream could not be reached")

    @staticmethod
    def _map_app_server_error(error):
        return GatewayError(error.status, error.code, error.message)

    def open_chat(self, payload):
        if getattr(self.auth_adapter, "adapter_version", "") != "real-v1":
            return self.open_upstream("POST", "/chat/completions", payload)
        if self.app_server is None:
            raise GatewayError(503, "app_server_unavailable", "Codex App Server is not configured")
        try:
            response = self.app_server.start_chat(payload)
            if not payload.get("stream") and hasattr(response, "iter_bytes"):
                try:
                    return _MemoryResponse(b"".join(response.iter_bytes()))
                finally:
                    response.close()
            return response
        except AppServerError as error:
            raise self._map_app_server_error(error)

    def open_models(self):
        if getattr(self.auth_adapter, "adapter_version", "") != "real-v1":
            return self.open_upstream("GET", "/models")
        if self.app_server is None:
            raise GatewayError(503, "app_server_unavailable", "Codex App Server is not configured")
        try:
            return self.app_server.list_models()
        except AppServerError as error:
            raise self._map_app_server_error(error)
