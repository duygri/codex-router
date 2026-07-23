import json
import os
import tempfile
import unittest

from codex_router.auth import AuthAdapter
from codex_router.config import RouterConfig
from codex_router.dashboard import build_status, render_html
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
        status = build_status(AuthAdapter(self.auth_path), store, config)
        self.assertEqual(status["auth"], "valid")
        self.assertEqual(status["adapter"], "synthetic-v1")
        self.assertNotIn("access_token", json.dumps(status))
        self.assertNotIn("SYNTHETIC_ACCESS_TOKEN_ONLY", json.dumps(status))

    def test_html_escapes_status_values(self):
        html = render_html({"auth": "valid", "adapter": "synthetic-v1"})
        self.assertIn("Codex Router", html)
        self.assertNotIn("SYNTHETIC_ACCESS_TOKEN_ONLY", html)

    def test_cli_has_serve_status_and_reset_commands(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["serve", "--port", "2020"]).port, 2020)
        self.assertEqual(parser.parse_args(["status"]).command, "status")
        self.assertEqual(parser.parse_args(["reset"]).command, "reset")


if __name__ == "__main__":
    unittest.main()
