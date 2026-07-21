import json
import os
import tempfile
import unittest
from unittest import mock

from codex_router import __main__ as cli
from codex_router.auth import AuthAdapter
from codex_router.config import RouterConfig
from codex_router.gateway import Gateway
from codex_router.server import run_server


class _FakeServer:
    def serve_forever(self):
        return None

    def server_close(self):
        return None


class CliIntegrationTests(unittest.TestCase):
    def make_file(self, content):
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(content)
        return path

    def test_codex_home_is_authoritative_and_explicit_file_wins(self):
        with tempfile.TemporaryDirectory() as codex_home:
            first_env = os.environ.copy()
            first_env.pop("CODEX_ROUTER_AUTH_FILE", None)
            first_env["CODEX_HOME"] = codex_home
            with mock.patch.dict(os.environ, first_env, clear=True):
                config = RouterConfig.from_env()
            self.assertEqual(config.auth_path, os.path.join(codex_home, "auth.json"))

            explicit = self.make_file("{}")
            second_env = os.environ.copy()
            second_env["CODEX_HOME"] = codex_home
            second_env["CODEX_ROUTER_AUTH_FILE"] = explicit
            with mock.patch.dict(os.environ, second_env, clear=True):
                config = RouterConfig.from_env()
            self.assertEqual(config.auth_path, explicit)

    def test_cli_created_server_receives_real_profile_and_router_key(self):
        auth_path = self.make_file(json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {
                "access_token": "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJleHAiOjQxMDI0NDQ4MDB9.REAL_V1_SANITIZED_SIGNATURE",
                "refresh_token": "REAL_V1_SANITIZED_REFRESH_TOKEN",
                "account_id": "00000000-0000-0000-0000-000000000000",
            },
        }))
        db_handle, db_path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(db_handle)
        self.addCleanup(lambda: os.path.exists(db_path) and os.remove(db_path))
        captured = {}

        def fake_create_server(gateway, host, port, status_provider=None, router_api_key=None, dashboard_data_provider=None):
            captured.update({"gateway": gateway, "host": host, "port": port, "router_api_key": router_api_key, "dashboard_data_provider": dashboard_data_provider})
            return _FakeServer()

        with mock.patch.dict(
            os.environ,
            {
                "CODEX_ROUTER_AUTH_FILE": auth_path,
                "CODEX_ROUTER_DATABASE": db_path,
                "CODEX_ROUTER_UPSTREAM_URL": "http://127.0.0.1:9000/v1",
                "CODEX_ROUTER_API_KEY": "router-secret",
                "CODEX_ROUTER_CODEX_COMMAND": "codex-test",
            },
            clear=False,
        ), mock.patch.object(cli, "create_server", side_effect=fake_create_server):
            result = cli.main_with_args(["serve", "--port", "20129"])
        self.assertEqual(result, 0)
        self.assertEqual(captured["router_api_key"], "router-secret")
        self.assertEqual(captured["gateway"].auth_adapter.adapter_version, "real-v1")
        self.assertEqual(captured["gateway"].app_server.command, "codex-test")
        self.assertIsNotNone(captured["dashboard_data_provider"])

    def test_run_server_passes_router_key_and_loopback(self):
        captured = {}

        def fake_create_server(gateway, host, port, status_provider=None, router_api_key=None, dashboard_data_provider=None):
            captured.update({"host": host, "port": port, "router_api_key": router_api_key})
            return _FakeServer()

        with mock.patch("codex_router.server.create_server", side_effect=fake_create_server):
            run_server(Gateway(AuthAdapter("missing.json", adapter_version="synthetic-v1"), "http://127.0.0.1:9000/v1"), router_api_key="router-secret")
        self.assertEqual(captured, {"host": "127.0.0.1", "port": 20128, "router_api_key": "router-secret"})


if __name__ == "__main__":
    unittest.main()
