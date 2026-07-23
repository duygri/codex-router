import os
import unittest
from unittest import mock

from codex_router import __main__ as cli
from codex_router import config as config_module


class CliIntegrationTests(unittest.TestCase):
    def test_start_parser_supports_explicit_browser_overrides(self):
        parser = cli.build_parser()
        try:
            start_args = parser.parse_args(["start"])
            browser_args = parser.parse_args(["start", "--browser"])
            no_browser_args = parser.parse_args(["start", "--no-browser"])
        except SystemExit as error:
            self.fail("start parser contract is missing: %s" % error)
        self.assertEqual(start_args.command, "start")
        self.assertTrue(browser_args.browser)
        self.assertFalse(no_browser_args.browser)
        self.assertEqual(parser.parse_args(["serve"]).command, "serve")
        self.assertEqual(parser.parse_args(["doctor"]).command, "doctor")

    def test_explicit_browser_flags_override_environment_policy(self):
        config = config_module.RouterConfig()
        config.browser_policy = "always"
        resolver = getattr(cli, "resolve_browser_policy", None)
        self.assertIsNotNone(resolver)
        if resolver is not None:
            self.assertEqual(resolver(config, cli.build_parser().parse_args(["start"])), "always")
            self.assertEqual(resolver(config, cli.build_parser().parse_args(["start", "--no-browser"])), "never")
            self.assertEqual(resolver(config, cli.build_parser().parse_args(["start", "--browser"])), "always")

    def test_invalid_start_configuration_exits_before_store_construction(self):
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_BROWSER": "invalid"}, clear=True), mock.patch.object(cli, "_open_store") as open_store:
            result = cli.main_with_args(["start"])
        self.assertEqual(result, 2)
        open_store.assert_not_called()

    def test_invalid_serve_configuration_keeps_exit_code_two(self):
        store = mock.Mock()
        server = mock.Mock()
        server.serve_forever.return_value = None
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_START_TIMEOUT": "0"}, clear=True), mock.patch.object(cli, "_open_store", return_value=store) as open_store, mock.patch.object(cli, "create_server", return_value=server):
            result = cli.main_with_args(["serve"])
        self.assertEqual(result, 2)
        open_store.assert_not_called()

    def test_doctor_reports_invalid_configuration_with_exit_code_two(self):
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_BROWSER": "invalid"}, clear=True), mock.patch.object(cli, "_open_store") as open_store:
            result = cli.main_with_args(["doctor"])
        self.assertEqual(result, 2)
        open_store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
