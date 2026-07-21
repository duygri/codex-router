import os
import unittest
from unittest import mock

from codex_router import config as config_module


class RouterConfigTests(unittest.TestCase):
    def validate(self, config):
        validator = getattr(config_module, "validate_router_config", None)
        self.assertIsNotNone(validator)
        return validator(config)

    def test_browser_policy_defaults_and_accepts_documented_values(self):
        for value in ("auto", "always", "never"):
            with mock.patch.dict(os.environ, {"CODEX_ROUTER_BROWSER": value}, clear=True):
                config = config_module.RouterConfig.from_env()
            self.assertEqual(config.browser_policy, value)
            self.validate(config)

    def test_invalid_browser_policy_is_preserved_until_validation(self):
        value = "sometimes"
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_BROWSER": value}, clear=True):
            config = config_module.RouterConfig.from_env()
        self.assertEqual(config.browser_policy, value)
        with self.assertRaises(Exception) as raised:
            self.validate(config)
        self.assertNotIn(value, str(raised.exception))

    def test_start_timeout_accepts_only_finite_values_from_one_through_five(self):
        for value in ("1", "2.5", "5"):
            with mock.patch.dict(os.environ, {"CODEX_ROUTER_START_TIMEOUT": value}, clear=True):
                config = config_module.RouterConfig.from_env()
            self.assertEqual(config.start_timeout, float(value))
            self.validate(config)

    def test_invalid_start_timeout_is_preserved_until_validation(self):
        for value in ("0.5", "5.1", "nan", "inf", "not-a-number"):
            with mock.patch.dict(os.environ, {"CODEX_ROUTER_START_TIMEOUT": value}, clear=True):
                config = config_module.RouterConfig.from_env()
            self.assertEqual(config.start_timeout, value)
            with self.assertRaises(Exception) as raised:
                self.validate(config)
            self.assertNotIn(value, str(raised.exception))

    def test_fallbacks_are_retained_and_capped_at_eight_entries(self):
        values = ",".join("gpt-%d" % index for index in range(8))
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_MODEL_FALLBACKS": values}, clear=True):
            config = config_module.RouterConfig.from_env()
        self.assertEqual(config.model_fallbacks, tuple("gpt-%d" % index for index in range(8)))
        self.validate(config)

        ninth = values + ",gpt-8"
        with mock.patch.dict(os.environ, {"CODEX_ROUTER_MODEL_FALLBACKS": ninth}, clear=True):
            config = config_module.RouterConfig.from_env()
        self.assertEqual(len(config.model_fallbacks), 9)
        with self.assertRaises(Exception) as raised:
            self.validate(config)
        self.assertNotIn("gpt-8", str(raised.exception))

    def test_every_fallback_is_validated_without_silent_skipping(self):
        for value in (
            "gpt bad",
            "gpt\nname",
            "gpt\rname",
            "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.payload.signature",
            "access_token=secret",
        ):
            with mock.patch.dict(os.environ, {"CODEX_ROUTER_MODEL_FALLBACKS": value}, clear=True):
                config = config_module.RouterConfig.from_env()
            with self.assertRaises(Exception) as raised:
                self.validate(config)
            self.assertNotIn(value, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
