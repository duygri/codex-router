import json
import os
import re
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout
from io import StringIO

from codex_router.config import ConfigError, RouterConfig, initialize_router_config
from codex_router import __main__ as cli


class RouterConfigTests(unittest.TestCase):
    def make_path(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: os.path.isdir(directory) and __import__("shutil").rmtree(directory))
        return os.path.join(directory, "router-config.json")

    def test_bootstrap_creates_and_reuses_a_private_router_key(self):
        path = self.make_path()

        first = initialize_router_config(path)
        second = initialize_router_config(path)

        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{43,128}", first))
        self.assertEqual(second, first)
        with open(path, "r", encoding="utf-8") as stream:
            self.assertEqual(json.load(stream), {"router_api_key": first})

    def test_from_env_loads_local_key_without_putting_it_in_metadata(self):
        path = self.make_path()
        key = initialize_router_config(path)

        with mock.patch.dict(os.environ, {"CODEX_ROUTER_CONFIG": path}, clear=True):
            config = RouterConfig.from_env()

        self.assertEqual(config.router_api_key, key)
        self.assertEqual(config.config_path, path)
        self.assertEqual(config.config_error, "")

    def test_environment_key_takes_precedence_over_local_file(self):
        path = self.make_path()
        initialize_router_config(path)
        env_key = "env-key-0123456789-0123456789-0123456789"
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_CONFIG": path, "CODEX_ROUTER_API_KEY": env_key}, clear=True):
            config = RouterConfig.from_env()
        self.assertEqual(config.router_api_key, env_key)

    def test_invalid_environment_key_fails_closed(self):
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_API_KEY": "short"}, clear=True):
            config = RouterConfig.from_env()
        self.assertEqual(config.router_api_key, "")
        self.assertEqual(config.config_error, "router api key is invalid")

    def test_invalid_local_key_fails_closed_without_generating_a_replacement(self):
        path = self.make_path()
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"router_api_key": "too-short"}, stream)

        with mock.patch.dict(os.environ, {"CODEX_ROUTER_CONFIG": path}, clear=True):
            config = RouterConfig.from_env()

        self.assertEqual(config.router_api_key, "")
        self.assertEqual(config.config_error, "router config is invalid")

    def test_bootstrap_rejects_existing_symlink(self):
        path = self.make_path()
        target = path + ".target"
        with open(target, "w", encoding="utf-8") as stream:
            stream.write("{}")
        try:
            os.symlink(target, path)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are unavailable in this Windows policy")
        with self.assertRaises(ConfigError):
            initialize_router_config(path)

    def test_cli_init_bootstraps_without_printing_the_key(self):
        path = self.make_path()
        output = StringIO()
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_CONFIG": path}, clear=True), redirect_stdout(output):
            result = cli.main_with_args(["init"])
        self.assertEqual(result, 0)
        with open(path, "r", encoding="utf-8") as stream:
            created = json.load(stream)["router_api_key"]
        self.assertNotIn(created, output.getvalue())
        self.assertIn("initialized", output.getvalue().lower())

    def test_cli_key_requires_explicit_show_to_print_secret(self):
        path = self.make_path()
        key = initialize_router_config(path)
        output = StringIO()
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_CONFIG": path}, clear=True), redirect_stdout(output):
            result = cli.main_with_args(["key"])
        self.assertEqual(result, 0)
        self.assertNotIn(key, output.getvalue())
        output = StringIO()
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_CONFIG": path}, clear=True), redirect_stdout(output):
            result = cli.main_with_args(["key", "--show"])
        self.assertEqual(result, 0)
        self.assertIn(key, output.getvalue())


if __name__ == "__main__":
    unittest.main()
