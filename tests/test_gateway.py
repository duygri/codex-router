import json
import os
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from codex_router.auth import AuthAdapter
from codex_router.gateway import Gateway, GatewayError
from codex_router.model_catalog import ModelCatalog
from codex_router.storage import MetadataStore
from codex_router.usage import UsageTracker


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

    def iter_bytes(self):
        body = self.read()
        if body:
            yield body

    def close(self):
        return None


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

        gateway = Gateway(AuthAdapter(self.make_auth_file(), adapter_version="synthetic-v1"), "http://127.0.0.1:9000/v1", opener=opener)
        response = gateway.open_upstream("POST", "/chat/completions", {"model": "codex"})
        self.assertEqual(response.status, 200)
        self.assertEqual(captured["request"].get_header("Authorization"), "Bearer SYNTHETIC_ACCESS_TOKEN_ONLY")
        self.assertEqual(captured["request"].get_header("Content-type"), "application/json")

    def test_missing_auth_maps_to_401_auth_required(self):
        gateway = Gateway(AuthAdapter("missing.json", adapter_version="synthetic-v1"), "http://127.0.0.1:9000/v1", opener=lambda *_: FakeResponse())
        with self.assertRaises(GatewayError) as raised:
            gateway.open_upstream("GET", "/models")
        self.assertEqual(raised.exception.status, 401)
        self.assertEqual(raised.exception.code, "auth_required")

    def test_upstream_429_is_not_retried(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)

        gateway = Gateway(AuthAdapter(self.make_auth_file(), adapter_version="synthetic-v1"), "http://127.0.0.1:9000/v1", opener=opener)
        with self.assertRaises(GatewayError) as raised:
            gateway.open_upstream("GET", "/models")
        self.assertEqual(raised.exception.status, 429)
        self.assertEqual(len(calls), 1)

    def test_stale_fingerprint_is_rejected(self):
        path = self.make_auth_file()
        adapter = AuthAdapter(path, adapter_version="synthetic-v1")
        loaded = adapter.load_session()
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("\n")
        gateway = Gateway(adapter, "http://127.0.0.1:9000/v1", opener=lambda *_: FakeResponse())
        with self.assertRaises(GatewayError) as raised:
            gateway.ensure_session_current(loaded.fingerprint)
        self.assertEqual(raised.exception.code, "auth_expired")

    def test_real_profile_refuses_env_bearer_forwarding(self):
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_ROUTER_AUTH_MODE": "env",
                "CODEX_ACCESS_TOKEN": "env-token-not-a-jwt",
                "CODEX_ROUTER_TOKEN_EXPIRES_AT": "2100-01-01T00:00:00Z",
            },
            clear=False,
        ):
            adapter = AuthAdapter("missing.json", adapter_version="real-v1")
            gateway = Gateway(adapter, "http://127.0.0.1:9000/v1", opener=lambda *_: FakeResponse())
            with self.assertRaises(GatewayError) as raised:
                gateway.open_upstream("GET", "/models")
        self.assertEqual(raised.exception.code, "direct_bearer_disabled")

    def test_upstream_401_maps_to_auth_expired_without_retry(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

        gateway = Gateway(
            AuthAdapter(self.make_auth_file(), adapter_version="synthetic-v1"),
            "http://127.0.0.1:9000/v1",
            opener=opener,
        )
        with self.assertRaises(GatewayError) as raised:
            gateway.open_upstream("GET", "/models")
        self.assertEqual(raised.exception.code, "auth_expired")
        self.assertEqual(len(calls), 1)

    def test_rejects_arbitrary_remote_upstream(self):
        gateway = Gateway(
            AuthAdapter(self.make_auth_file(), adapter_version="synthetic-v1"),
            "https://example.com/v1",
            opener=lambda *args, **kwargs: FakeResponse(),
        )
        with self.assertRaises(GatewayError) as raised:
            gateway.open_upstream("GET", "/models")
        self.assertEqual(raised.exception.code, "unsafe_upstream")

    def test_rejects_non_loopback_http_upstream(self):
        gateway = Gateway(
            AuthAdapter(self.make_auth_file(), adapter_version="synthetic-v1"),
            "http://example.com/v1",
            opener=lambda *args, **kwargs: FakeResponse(),
        )
        with self.assertRaises(GatewayError) as raised:
            gateway.open_upstream("GET", "/models")
        self.assertEqual(raised.exception.code, "insecure_upstream")

    def test_real_profile_uses_app_server_for_chat_without_reading_bearer(self):
        app_server = mock.Mock()
        app_server.start_chat.return_value = FakeResponse()
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
        )
        payload = {"messages": [{"role": "user", "content": "hello"}]}
        response = gateway.open_chat(payload)
        self.assertEqual(response.status, 200)
        app_server.start_chat.assert_called_once_with(payload)

    def test_real_profile_resolves_codex_alias_before_starting_chat(self):
        app_server = mock.Mock()
        app_server.start_chat.return_value = FakeResponse()
        catalog = ModelCatalog(lambda: [{"id": "gpt-router"}])
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
            model_catalog=catalog,
        )

        gateway.open_chat({"model": "codex", "messages": [{"role": "user", "content": "hello"}]})

        app_server.start_chat.assert_called_once_with({
            "model": "gpt-router",
            "messages": [{"role": "user", "content": "hello"}],
        })

    def test_real_profile_lists_models_from_app_server(self):
        app_server = mock.Mock()
        app_server.list_models.return_value = FakeResponse()
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
        )
        response = gateway.open_models()
        self.assertEqual(response.status, 200)
        app_server.list_models.assert_called_once_with()

    def test_real_profile_lists_catalog_alias_and_normalized_models(self):
        app_server = mock.Mock()
        catalog = ModelCatalog(lambda: [{"id": "gpt-router"}, {"model": "gpt-fast"}])
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
            model_catalog=catalog,
        )

        response = gateway.open_models()
        payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual([item["id"] for item in payload["data"]], ["codex", "gpt-router", "gpt-fast"])
        self.assertEqual(payload["data"][0]["owned_by"], "codex-router")

    def test_chat_usage_completes_when_response_is_read(self):
        handle, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        store = MetadataStore(path)
        self.addCleanup(store.close)
        tracker = UsageTracker(store)
        app_server = mock.Mock()
        app_server.start_chat.return_value = FakeResponse()
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
            model_catalog=ModelCatalog(lambda: [{"id": "gpt-router"}]),
            usage_tracker=tracker,
        )

        response = gateway.open_chat({"model": "codex", "messages": [{"role": "user", "content": "hello"}]})
        response.read()

        self.assertEqual(tracker.snapshot()["completed_requests"], 1)
        self.assertEqual(tracker.snapshot()["active_requests"], 0)

    def test_chat_usage_is_cancelled_when_stream_is_closed_early(self):
        handle, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        store = MetadataStore(path)
        self.addCleanup(store.close)
        tracker = UsageTracker(store)
        app_server = mock.Mock()
        app_server.start_chat.return_value = FakeResponse(content_type="text/event-stream")
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
            model_catalog=ModelCatalog(lambda: [{"id": "gpt-router"}]),
            usage_tracker=tracker,
        )

        response = gateway.open_chat({"stream": True, "messages": [{"role": "user", "content": "hello"}]})
        response.close()

        self.assertEqual(tracker.snapshot()["cancelled_requests"], 1)
        self.assertEqual(tracker.snapshot()["active_requests"], 0)

    def test_real_profile_adapts_text_responses_api_to_codex(self):
        app_server = mock.Mock()
        app_server.start_chat.return_value = FakeResponse(body=json.dumps({
            "id": "chatcmpl-test",
            "model": "gpt-router",
            "choices": [{"message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
        }).encode("utf-8"))
        catalog = ModelCatalog(lambda: [{"id": "gpt-router"}])
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
            model_catalog=catalog,
        )

        response = gateway.open_responses({
            "model": "codex",
            "instructions": "Be concise.",
            "input": "Say hello",
        })
        payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["object"], "response")
        self.assertEqual(payload["output_text"], "hello")
        app_server.start_chat.assert_called_once_with({
            "model": "gpt-router",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Say hello"},
            ],
            "stream": False,
        })

    def test_responses_api_rejects_tools_and_multimodal_input(self):
        app_server = mock.Mock()
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
            model_catalog=ModelCatalog(lambda: [{"id": "gpt-router"}]),
        )
        with self.assertRaises(GatewayError) as raised:
            gateway.open_responses({"input": "hello", "tools": []})
        self.assertEqual(raised.exception.code, "unsupported_request_options")
        with self.assertRaises(GatewayError) as raised:
            gateway.open_responses({"input": [{"type": "message", "role": "user", "content": [{"type": "input_image", "image_url": "x"}]}]})
        self.assertEqual(raised.exception.code, "unsupported_input")
        app_server.start_chat.assert_not_called()

    def test_real_profile_streams_responses_text_events(self):
        app_server = mock.Mock()
        app_server.start_chat.return_value = FakeResponse(
            body=(
                b'data: {"id":"chatcmpl-test","choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
                b'data: {"id":"chatcmpl-test","choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
                b'data: {"id":"chatcmpl-test","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b'data: [DONE]\n\n'
            ),
            content_type="text/event-stream",
        )
        gateway = Gateway(
            AuthAdapter("missing.json", adapter_version="real-v1"),
            "https://api.openai.com/v1",
            app_server=app_server,
            model_catalog=ModelCatalog(lambda: [{"id": "gpt-router"}]),
        )

        body = gateway.open_responses({"model": "codex", "input": "hello", "stream": True}).read().decode("utf-8")

        self.assertIn("event: response.created", body)
        self.assertIn("event: response.output_text.delta", body)
        self.assertIn('"delta":"hello"', body)
        self.assertIn("event: response.completed", body)


if __name__ == "__main__":
    unittest.main()
