import json
import os
import tempfile
import unittest
from urllib.error import HTTPError

from codex_router.auth import AuthAdapter
from codex_router.gateway import Gateway, GatewayError


class FakeResponse:
    def __init__(self, status=200, body=b'{"ok":true}', content_type="application/json"):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.body = body

    def read(self, size=-1):
        if size == -1:
            value, self.body = self.body, b""
            return value
        value, self.body = self.body[:size], self.body[size:]
        return value

    def getcode(self):
        return self.status


class GatewayTests(unittest.TestCase):
    def make_auth_file(self):
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({
                "schema_version": 1,
                "access_token": "SYNTHETIC_ACCESS_TOKEN_ONLY",
                "expires_at": "2099-01-01T00:00:00Z",
            }, stream)
        return path

    def test_builds_authorized_upstream_request(self):
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        gateway = Gateway(AuthAdapter(self.make_auth_file()), "http://upstream.test/v1", opener=opener)
        response = gateway.open_upstream("POST", "/chat/completions", {"model": "codex"})
        self.assertEqual(response.status, 200)
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer SYNTHETIC_ACCESS_TOKEN_ONLY")
        self.assertEqual(captured["request"].get_header("Content-type"), "application/json")

    def test_missing_auth_maps_to_401_auth_required(self):
        gateway = Gateway(AuthAdapter("missing.json"), "http://upstream.test/v1", opener=lambda *_: FakeResponse())
        with self.assertRaises(GatewayError) as raised:
            gateway.open_upstream("GET", "/models")
        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.code, "auth_required")

    def test_upstream_429_is_not_retried(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)

        gateway = Gateway(AuthAdapter(self.make_auth_file()), "http://upstream.test/v1", opener=opener)
        with self.assertRaises(GatewayError) as raised:
            gateway.open_upstream("GET", "/models")
        self.assertEqual(raised.exception.status, 429)
        self.assertEqual(len(calls), 1)

    def test_stale_fingerprint_is_rejected(self):
        path = self.make_auth_file()
        adapter = AuthAdapter(path)
        loaded = adapter.load_session()
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("\n")
        gateway = Gateway(adapter, "http://upstream.test/v1", opener=lambda *_: FakeResponse())
        with self.assertRaises(GatewayError) as raised:
            gateway.ensure_session_current(loaded.fingerprint)
        self.assertEqual(raised.exception.code, "auth_expired")


if __name__ == "__main__":
    unittest.main()
