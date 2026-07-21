import json
import os
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from io import StringIO

from codex_router import __main__ as cli
from codex_router.auth import AuthAdapter
from codex_router.config import RouterConfig
from codex_router.gateway import Gateway
from codex_router.readiness import CheckResult, ReadinessReport
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

        def fake_create_server(gateway, host, port, status_provider=None, router_api_key=None, dashboard_data_provider=None, readiness_provider=None):
            captured.update({"gateway": gateway, "host": host, "port": port, "router_api_key": router_api_key, "dashboard_data_provider": dashboard_data_provider, "readiness_provider": readiness_provider})
            return _FakeServer()

        with mock.patch.dict(
            os.environ,
            {
                "CODEX_ROUTER_AUTH_FILE": auth_path,
                "CODEX_ROUTER_DATABASE": db_path,
                "CODEX_ROUTER_UPSTREAM_URL": "http://127.0.0.1:9000/v1",
                "CODEX_ROUTER_API_KEY": "router-secret-0123456789-0123456789-0123456789",
                "CODEX_ROUTER_CODEX_COMMAND": "codex-test",
                "CODEX_ROUTER_QUEUE_SIZE": "4",
                "CODEX_ROUTER_QUEUE_TIMEOUT": "1.5",
            },
            clear=False,
        ), mock.patch.object(cli, "create_server", side_effect=fake_create_server):
            result = cli.main_with_args(["serve", "--port", "20129"])
        self.assertEqual(result, 0)
        self.assertEqual(captured["router_api_key"], "router-secret-0123456789-0123456789-0123456789")
        self.assertEqual(captured["gateway"].auth_adapter.adapter_version, "real-v1")
        self.assertEqual(captured["gateway"].app_server.command, "codex-test")
        self.assertEqual(captured["gateway"].app_server.queue_size, 4)
        self.assertEqual(captured["gateway"].app_server.queue_timeout, 1.5)
        self.assertIsNotNone(captured["dashboard_data_provider"])
        self.assertIsNotNone(captured["readiness_provider"])

    def test_run_server_passes_router_key_and_loopback(self):
        captured = {}

        def fake_create_server(gateway, host, port, status_provider=None, router_api_key=None, dashboard_data_provider=None):
            captured.update({"host": host, "port": port, "router_api_key": router_api_key})
            return _FakeServer()

        with mock.patch("codex_router.server.create_server", side_effect=fake_create_server):
            run_server(Gateway(AuthAdapter("missing.json", adapter_version="synthetic-v1"), "http://127.0.0.1:9000/v1"), router_api_key="router-secret")
        self.assertEqual(captured, {"host": "127.0.0.1", "port": 20128, "router_api_key": "router-secret"})

    def test_doctor_runs_before_store_and_emits_safe_json(self):
        with tempfile.TemporaryDirectory() as root:
            database_path = os.path.join(root, "metadata", "router.sqlite3")
            report = ReadinessReport("ready", {
                "config": CheckResult.ok("Configuration is valid"),
                "codex_cli": CheckResult.skipped("Not required for synthetic-v1"),
                "app_server": CheckResult.skipped("Not required for synthetic-v1"),
                "model_catalog": CheckResult.skipped("Not required for synthetic-v1"),
            })
            output = StringIO()
            with mock.patch.dict(os.environ, {
                "CODEX_ROUTER_ADAPTER": "synthetic-v1",
                "CODEX_ROUTER_DATABASE": database_path,
                "CODEX_ROUTER_API_KEY": "router-secret-0123456789-0123456789-0123456789",
            }, clear=True), mock.patch.object(cli, "doctor_report", return_value=report) as doctor, redirect_stdout(output):
                result = cli.main_with_args(["doctor"])

            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "ready")
            self.assertFalse(os.path.exists(database_path))
            doctor.assert_called_once()

    def test_doctor_rejects_invalid_config_without_running_probe(self):
        output = StringIO()
        with mock.patch.dict(os.environ, {
            "CODEX_ROUTER_ADAPTER": "unknown-v1",
            "CODEX_ROUTER_API_KEY": "router-secret-0123456789-0123456789-0123456789",
        }, clear=True), redirect_stdout(output):
            result = cli.main_with_args(["doctor"])

        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "invalid_config")


if __name__ == "__main__":
    unittest.main()
