import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from codex_router.auth import AuthAdapter
from codex_router.gateway import Gateway
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
            AuthAdapter(self.auth_path),
            "http://127.0.0.1:%s/v1" % self.upstream.server_port,
        )
        self.server = create_server(gateway, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        headers = {} if encoded is None else {"Content-Type": "application/json"}
        connection.request(method, path, encoded, headers)
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
        status, _, body = self.request("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertIn(b'"object":"list"', body)
        status, _, body = self.request("POST", "/v1/chat/completions", {"model": "codex"})
        self.assertEqual(status, 200)
        self.assertIn(b"chatcmpl-test", body)

    def test_streaming_response_is_passthrough(self):
        status, headers, body = self.request("POST", "/v1/chat/completions", {"stream": True})
        self.assertEqual(status, 200)
        self.assertIn(("Content-Type", "text/event-stream"), headers)
        self.assertIn(b"[DONE]", body)

    def test_invalid_json_returns_safe_400(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        connection.request("POST", "/v1/chat/completions", b"not-json", {"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        self.assertEqual(response.status, 400)
        self.assertIn(b'"code":"invalid_json"', body)


if __name__ == "__main__":
    unittest.main()
