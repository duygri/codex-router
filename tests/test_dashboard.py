import json
import os
import tempfile
import unittest

from codex_router.auth import AuthAdapter
from codex_router.config import RouterConfig
from codex_router.dashboard import build_dashboard_data, build_status, render_html
from codex_router.__main__ import build_parser
from codex_router.storage import MetadataStore


class DashboardTests(unittest.TestCase):
    def setUp(self):
        handle, self.auth_path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(self.auth_path) and os.remove(self.auth_path))
        with open(self.auth_path, "w", encoding="utf-8") as stream:
            json.dump({
                "schema_version": 1,
                "access_token": "SYNTHETIC_ACCESS_TOKEN_ONLY",
                "expires_at": "2099-01-01T00:00:00Z",
            }, stream)
        handle, self.db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(self.db_path) and os.remove(self.db_path))

    def test_status_has_safe_fields_only(self):
        store = MetadataStore(self.db_path)
        self.addCleanup(store.close)
        store.set("adapter_version", "synthetic-v1")
        config = RouterConfig(auth_path=self.auth_path, database_path=self.db_path)
        status = build_status(AuthAdapter(self.auth_path, adapter_version="synthetic-v1"), store, config)
        self.assertEqual(status["auth"], "valid")
        self.assertEqual(status["adapter"], "synthetic-v1")
        self.assertNotIn("access_token", json.dumps(status))
        self.assertNotIn("SYNTHETIC_ACCESS_TOKEN_ONLY", json.dumps(status))

    def test_html_escapes_status_values(self):
        html = render_html({"auth": "<script>bad</script>", "adapter": "synthetic-v1"})
        self.assertIn("Codex Router", html)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)
        self.assertNotIn("SYNTHETIC_ACCESS_TOKEN_ONLY", html)

    def test_dashboard_has_offline_operations_layout_and_accessibility(self):
        html = render_html({"auth": "valid", "adapter": "real-v1", "transport": "codex-app-server"})
        self.assertIn("Operations", html)
        self.assertIn("Model catalog", html)
        self.assertIn("Usage", html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("prefers-reduced-motion", html)
        self.assertIn("@media (min-width: 768px)", html)
        self.assertIn("Refresh dashboard", html)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("😀", html)

    def test_real_status_advertises_app_server_and_safe_capabilities(self):
        config = RouterConfig(auth_path="missing.json", adapter_version="real-v1")
        status = build_status(AuthAdapter("missing.json", adapter_version="real-v1"), config=config)
        self.assertEqual(status["transport"], "codex-app-server")
        self.assertEqual(status["approval_policy"], "on-request")
        self.assertEqual(status["sandbox"], "read-only")

    def test_dashboard_data_has_typed_envelope_and_models(self):
        class FakeUsage:
            def snapshot(self):
                return {
                    "total_requests": 2,
                    "completed_requests": 1,
                    "failed_requests": 1,
                    "cancelled_requests": 0,
                    "active_requests": 0,
                    "last_request_at": "2026-07-21T00:00:00Z",
                    "by_model": [{"model": "gpt-test", "requests": 2}],
                }

        class FakeGateway:
            usage_tracker = FakeUsage()

            def dashboard_models(self):
                return [{"id": "codex", "alias": "codex", "owned_by": "codex-router", "available": True}]

        config = RouterConfig(auth_path=self.auth_path, database_path=self.db_path, adapter_version="real-v1")
        data = build_dashboard_data(AuthAdapter(self.auth_path, adapter_version="real-v1"), None, config, FakeGateway())

        self.assertEqual(data["status"]["state"], "ok")
        self.assertIn("session", data["status"])
        self.assertEqual(data["models"][0]["id"], "codex")
        self.assertEqual(data["usage"]["total_requests"], 2)
        self.assertFalse(data["capabilities"]["responses"])
        self.assertIsNone(data["error"])
        self.assertNotIn("SYNTHETIC_ACCESS_TOKEN_ONLY", json.dumps(data))

    def test_dashboard_data_degrades_without_leaking_exception_details(self):
        class FakeGateway:
            usage_tracker = None

            def dashboard_models(self):
                raise RuntimeError("prompt=secret should not escape")

        config = RouterConfig(auth_path="missing.json", adapter_version="real-v1")
        data = build_dashboard_data(AuthAdapter("missing.json", adapter_version="real-v1"), None, config, FakeGateway())

        self.assertEqual(data["status"]["state"], "degraded")
        self.assertEqual(data["models"], [])
        self.assertEqual(data["error"]["code"], "dashboard_data_unavailable")
        self.assertNotIn("prompt=secret", json.dumps(data))

    def test_cli_has_serve_status_and_reset_commands(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["serve", "--port", "2020"]).port, 2020)
        self.assertEqual(parser.parse_args(["status"]).command, "status")
        self.assertEqual(parser.parse_args(["reset"]).command, "reset")


if __name__ == "__main__":
    unittest.main()
