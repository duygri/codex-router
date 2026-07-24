import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from codex_router.auth import AuthAdapter
from codex_router.gateway import Gateway
from codex_router.readiness import CheckResult, ReadinessReport
from codex_router.server import create_server


class FakeUpstreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v1/models":
            body = b'{"object":"list","data":[]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if payload.get("stream"):
            body = b"data: {\"delta\":\"hello\"}\n\ndata: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b'{"id":"chatcmpl-test","choices":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstreamHandler)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)
        handle, self.auth_path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(self.auth_path) and os.remove(self.auth_path))
        with open(self.auth_path, "w", encoding="utf-8") as stream:
            json.dump({
                "schema_version": 1,
                "access_token": "SYNTHETIC_ACCESS_TOKEN_ONLY",
                "expires_at": "2099-01-01T00:00:00Z",
            }, stream)
        gateway = Gateway(
            AuthAdapter(self.auth_path, adapter_version="synthetic-v1"),
            "http://127.0.0.1:%s/v1" % self.upstream.server_port,
        )
        self.readiness_calls = 0
        self.readiness_report = ReadinessReport("ready", {
            "config": CheckResult.ok("Configuration is valid"),
            "codex_cli": CheckResult.skipped("Not required for synthetic-v1"),
            "app_server": CheckResult.skipped("Not required for synthetic-v1"),
            "model_catalog": CheckResult.skipped("Not required for synthetic-v1"),
        })

        def readiness_provider():
            self.readiness_calls += 1
            return self.readiness_report

        self.server = create_server(
            gateway,
            "127.0.0.1",
            0,
            router_api_key="router-secret",
            readiness_provider=readiness_provider,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        request_headers = {} if encoded is None else {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)
        connection.request(method, path, encoded, request_headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, response.getheaders(), data

    def test_health_is_local_and_redacts_auth(self):
        status, _, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIn(b'"auth":"valid"', body)
        self.assertNotIn(b"SYNTHETIC_ACCESS_TOKEN_ONLY", body)

    def test_models_and_chat_forward(self):
        status, _, body = self.request("GET", "/v1/models", headers={"X-Codex-Router-Key": "router-secret"})
        self.assertEqual(status, 200)
        self.assertIn(b'"object":"list"', body)
        status, _, body = self.request("POST", "/v1/chat/completions", {"model": "codex"}, {"X-Codex-Router-Key": "router-secret"})
        self.assertEqual(status, 200)
        self.assertIn(b"chatcmpl-test", body)

    def test_streaming_response_is_passthrough(self):
        status, headers, body = self.request("POST", "/v1/chat/completions", {"stream": True}, {"X-Codex-Router-Key": "router-secret"})
        self.assertEqual(status, 200)
        self.assertIn(("Content-Type", "text/event-stream"), headers)
        self.assertIn(b"[DONE]", body)

    def test_responses_route_is_explicitly_rejected_for_synthetic_adapter(self):
        status, _, body = self.request(
            "POST",
            "/v1/responses",
            {"input": "hello"},
            {"X-Codex-Router-Key": "router-secret"},
        )
        self.assertEqual(status, 501)
        self.assertIn(b'"code":"responses_not_supported"', body)

    def test_v1_requires_router_key(self):
        status, _, body = self.request("GET", "/v1/models")
        self.assertEqual(status, 401)
        self.assertIn(b'"code":"router_auth_required"', body)

        status, _, body = self.request("GET", "/v1/models", headers={"X-Codex-Router-Key": "wrong"})
        self.assertEqual(status, 403)
        self.assertIn(b'"code":"router_auth_invalid"', body)

    def test_status_is_not_cacheable_and_request_id_is_safe(self):
        status, headers, _ = self.request("GET", "/status", headers={"X-Request-ID": "bad value"})
        self.assertEqual(status, 200)
        self.assertIn(("Cache-Control", "no-store"), headers)
        request_ids = [value for name, value in headers if name == "X-Request-ID"]
        self.assertTrue(request_ids)
        self.assertNotIn("\n", request_ids[0])

    def test_dashboard_data_is_safe_local_json_without_router_key(self):
        dashboard_server = create_server(
            Gateway(AuthAdapter(self.auth_path, adapter_version="synthetic-v1"), "http://127.0.0.1:9000/v1"),
            "127.0.0.1",
            0,
            router_api_key="router-secret",
            dashboard_data_provider=lambda: {
                "status": {"state": "ok"},
                "models": [{"id": "codex", "alias": "codex", "owned_by": "codex-router", "available": True}],
                "usage": {"total_requests": 0},
                "capabilities": {"tools": False},
                "error": None,
            },
        )
        thread = threading.Thread(target=dashboard_server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(dashboard_server.server_close)
        self.addCleanup(dashboard_server.shutdown)

        connection = http.client.HTTPConnection("127.0.0.1", dashboard_server.server_port, timeout=5)
        connection.request("GET", "/dashboard/data")
        response = connection.getresponse()
        body = response.read()
        headers = response.getheaders()
        connection.close()

        self.assertEqual(response.status, 200)
        self.assertIn(("Content-Type", "application/json"), headers)
        self.assertIn(("Cache-Control", "no-store"), headers)
        self.assertIn(b'"models"', body)
        self.assertNotIn(b"router-secret", body)
        self.assertNotIn(b"SYNTHETIC_ACCESS_TOKEN_ONLY", body)
        self.assertEqual(self.readiness_calls, 0)

    def test_ready_returns_exact_safe_envelope_and_maps_not_ready(self):
        status, _, body = self.request("GET", "/ready")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(set(payload["checks"]), {"config", "codex_cli", "app_server", "model_catalog"})
        self.assertEqual(self.readiness_calls, 1)

        self.readiness_report = ReadinessReport("not_ready", {
            "config": CheckResult.ok("Configuration is valid"),
            "codex_cli": CheckResult.failure("codex_cli_unavailable", "Codex CLI is unavailable"),
            "app_server": CheckResult.skipped("Not checked because a prerequisite failed"),
            "model_catalog": CheckResult.skipped("Not checked because a prerequisite failed"),
        })
        status, _, body = self.request("GET", "/ready")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body.decode("utf-8"))["status"], "not_ready")

    def test_non_loopback_bind_is_refused_even_with_router_key(self):
        gateway = Gateway(AuthAdapter(self.auth_path, adapter_version="synthetic-v1"), "http://127.0.0.1:9000/v1")
        with self.assertRaises(ValueError):
            create_server(gateway, "0.0.0.0", 0, router_api_key="router-secret")

    def test_invalid_json_returns_safe_400(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request("POST", "/v1/chat/completions", b"not-json", {"Content-Type": "application/json", "X-Codex-Router-Key": "router-secret"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        self.assertEqual(response.status, 400)
        self.assertIn(b'"code":"invalid_json"', body)

    def test_real_app_server_routes_do_not_forward_to_public_api(self):
        from unittest import mock

        app_server = mock.Mock()
        app_server.list_models.return_value = type("Response", (), {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "read": lambda self: b'{"object":"list","data":[]}',
        })()
        app_server.start_chat.return_value = type("Response", (), {
            "status": 200,
            "headers": {"Content-Type": "application/json"},
            "read": lambda self: b'{"choices":[]}',
        })()
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
        )
        server = create_server(gateway, "127.0.0.1", 0, router_api_key="router-secret")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def request_to_server(method, path, body=None, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            encoded = None if body is None else json.dumps(body).encode("utf-8")
            request_headers = {} if encoded is None else {"Content-Type": "application/json"}
            if headers:
                request_headers.update(headers)
            connection.request(method, path, encoded, request_headers)
            response = connection.getresponse()
            data = response.read()
            connection.close()
            return response.status, response.getheaders(), data

        status, _, body = request_to_server("GET", "/v1/models", headers={"X-Codex-Router-Key": "router-secret"})
        self.assertEqual(status, 200)
        self.assertIn(b'"object":"list"', body)
        status, _, _ = request_to_server(
            "POST",
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hello"}]},
            {"X-Codex-Router-Key": "router-secret"},
        )
        self.assertEqual(status, 200)
        app_server.list_models.assert_called_once_with()
        app_server.start_chat.assert_called_once()


if __name__ == "__main__":
    unittest.main()
