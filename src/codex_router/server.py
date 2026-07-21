"""Loopback HTTP server for the local Codex gateway."""

import json
import re
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .gateway import GatewayError
from .dashboard import build_status, render_html


MAX_BODY_BYTES = 1024 * 1024


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id(handler):
    candidate = handler.headers.get("X-Request-ID", "")
    return candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else uuid.uuid4().hex


def _is_loopback_bind(host):
    return (host or "").lower().rstrip(".") in ("127.0.0.1", "localhost", "::1")


def create_server(gateway, host="127.0.0.1", port=20128, status_provider=None, router_api_key=None, dashboard_data_provider=None, readiness_provider=None):
    if not _is_loopback_bind(host):
        raise ValueError("Codex Router only supports loopback binds")

    class RouterHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            # Deliberately avoid default access logs, which can expose request data.
            return

        def _send_json(self, status, payload):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", _request_id(self))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, body):
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("X-Request-ID", _request_id(self))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _send_error(self, error):
            self._send_json(error.status, {"error": {"code": error.code, "message": error.message}})

        def _require_router_key(self):
            if not router_api_key:
                raise GatewayError(401, "router_auth_required", "Set CODEX_ROUTER_API_KEY before using /v1 routes")
            supplied = self.headers.get("X-Codex-Router-Key", "")
            import hmac
            if not supplied:
                raise GatewayError(401, "router_auth_required", "X-Codex-Router-Key is required")
            if not hmac.compare_digest(supplied, router_api_key):
                raise GatewayError(403, "router_auth_invalid", "X-Codex-Router-Key is invalid")

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise GatewayError(400, "invalid_content_length", "Content-Length must be valid")
            if length <= 0 or length > MAX_BODY_BYTES:
                raise GatewayError(400, "invalid_body", "Request body is missing or too large")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise GatewayError(400, "invalid_json", "Request body must be valid JSON")
            if not isinstance(payload, dict):
                raise GatewayError(400, "invalid_payload", "Request body must be a JSON object")
            return payload

        def _proxy(self, response):
            status = response.getcode() if hasattr(response, "getcode") else getattr(response, "status", 200)
            status = status or 200
            content_type = response.headers.get("Content-Type", "application/json")
            streaming = "text/event-stream" in content_type.lower()
            content_length = response.headers.get("Content-Length")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Request-ID", _request_id(self))
            self.send_header("Cache-Control", "no-store")
            if content_length is not None:
                self.send_header("Content-Length", content_length)
            else:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            try:
                if hasattr(response, "iter_bytes"):
                    for chunk in response.iter_bytes():
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                elif streaming:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                else:
                    self.wfile.write(response.read())
            except (BrokenPipeError, ConnectionResetError):
                if hasattr(response, "close"):
                    response.close()
            finally:
                if hasattr(response, "close"):
                    response.close()

        def do_GET(self):
            if self.path == "/ready":
                try:
                    report = readiness_provider() if readiness_provider else None
                    if report is None:
                        payload = {
                            "status": "not_ready",
                            "checks": {
                                "config": {"ok": False, "code": "diagnostic_failed", "message": "Readiness is not configured"},
                                "codex_cli": {"ok": True, "code": "skipped", "message": "Not checked because a prerequisite failed"},
                                "app_server": {"ok": True, "code": "skipped", "message": "Not checked because a prerequisite failed"},
                                "model_catalog": {"ok": True, "code": "skipped", "message": "Not checked because a prerequisite failed"},
                            },
                        }
                    else:
                        payload = report.to_dict() if hasattr(report, "to_dict") else report
                    self._send_json(200 if payload.get("status") == "ready" else 503, payload)
                except Exception:
                    self._send_json(503, {
                        "status": "not_ready",
                        "checks": {
                            "config": {"ok": False, "code": "diagnostic_failed", "message": "Diagnostic check failed"},
                            "codex_cli": {"ok": True, "code": "skipped", "message": "Not checked because a prerequisite failed"},
                            "app_server": {"ok": True, "code": "skipped", "message": "Not checked because a prerequisite failed"},
                            "model_catalog": {"ok": True, "code": "skipped", "message": "Not checked because a prerequisite failed"},
                        },
                    })
                return
            if self.path == "/dashboard/data":
                data = dashboard_data_provider() if dashboard_data_provider else {
                    "status": {"state": "degraded", "message": "Dashboard data is not configured."},
                    "models": [],
                    "usage": {},
                    "capabilities": {"chat_completions": True, "responses": True, "responses_text_only": True, "tools": False, "multimodal": False, "router_key_configured": False, "queue_size": 2, "queue_timeout_seconds": 30.0},
                    "endpoint": {"base_url": "http://127.0.0.1:20128/v1", "auth_header": "X-Codex-Router-Key", "model_alias": "codex", "router_key_configured": False},
                    "error": {"code": "dashboard_data_unavailable", "message": "Dashboard data is not configured."},
                }
                self._send_json(200, data)
                return
            if self.path == "/":
                status = status_provider() if status_provider else build_status(gateway.auth_adapter)
                self._send_html(render_html(status))
                return
            if self.path == "/status":
                status = status_provider() if status_provider else build_status(gateway.auth_adapter)
                self._send_json(200, status)
                return
            if self.path == "/health":
                auth = gateway.auth_adapter.health_check()
                self._send_json(200, {
                    "status": "ok",
                    "auth": auth.status.value,
                    "adapter": gateway.auth_adapter.adapter_version,
                })
                return
            try:
                if self.path.startswith("/v1/"):
                    self._require_router_key()
                if self.path == "/v1/models":
                    self._proxy(gateway.open_models())
                    return
                raise GatewayError(404, "not_found", "Route not found")
            except GatewayError as error:
                self._send_error(error)

        def do_POST(self):
            try:
                if self.path.startswith("/v1/"):
                    self._require_router_key()
                if self.path not in ("/v1/chat/completions", "/v1/responses"):
                    raise GatewayError(404, "not_found", "Route not found")
                payload = self._read_json()
                response = gateway.open_responses(payload) if self.path == "/v1/responses" else gateway.open_chat(payload)
                self._proxy(response)
            except GatewayError as error:
                self._send_error(error)

    return ThreadingHTTPServer((host, port), RouterHandler)


def run_server(gateway, host="127.0.0.1", port=20128, router_api_key=None, readiness_provider=None):
    kwargs = {"router_api_key": router_api_key}
    if readiness_provider is not None:
        kwargs["readiness_provider"] = readiness_provider
    server = create_server(gateway, host, port, **kwargs)
    try:
        server.serve_forever()
    finally:
        server.server_close()
