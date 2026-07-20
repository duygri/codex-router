"""Loopback HTTP server for the local Codex gateway."""

import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .gateway import GatewayError


MAX_BODY_BYTES = 1024 * 1024


def _request_id(handler):
    return handler.headers.get("X-Request-ID") or uuid.uuid4().hex


def create_server(gateway, host="127.0.0.1", port=20128):
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
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, error):
            self._send_json(error.status, {"error": {"code": error.code, "message": error.message}})

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
            status = response.getcode() or 200
            content_type = response.headers.get("Content-Type", "application/json")
            streaming = "text/event-stream" in content_type.lower()
            content_length = response.headers.get("Content-Length")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Request-ID", _request_id(self))
            if content_length is not None:
                self.send_header("Content-Length", content_length)
            else:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            if streaming:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            else:
                self.wfile.write(response.read())

        def do_GET(self):
            if self.path == "/health":
                auth = gateway.auth_adapter.health_check()
                self._send_json(200, {
                    "status": "ok",
                    "auth": auth.status.value,
                    "adapter": gateway.auth_adapter.adapter_version,
                })
                return
            try:
                if self.path == "/v1/models":
                    self._proxy(gateway.open_upstream("GET", "/models"))
                    return
                raise GatewayError(404, "not_found", "Route not found")
            except GatewayError as error:
                self._send_error(error)

        def do_POST(self):
            try:
                if self.path != "/v1/chat/completions":
                    raise GatewayError(404, "not_found", "Route not found")
                payload = self._read_json()
                self._proxy(gateway.open_upstream("POST", "/chat/completions", payload))
            except GatewayError as error:
                self._send_error(error)

    return ThreadingHTTPServer((host, port), RouterHandler)


def run_server(gateway, host="127.0.0.1", port=20128):
    server = create_server(gateway, host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
