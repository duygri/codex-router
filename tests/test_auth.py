import base64
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from codex_router.auth import AuthAdapter, RefreshOutcome, SessionStatus
from codex_router.redaction import redact_text


FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "auth")


class AuthAdapterTests(unittest.TestCase):
    def copy_fixture(self, name):
        source = os.path.join(FIXTURE_ROOT, name)
        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        with open(source, "rb") as input_file, open(path, "wb") as output_file:
            output_file.write(input_file.read())
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path

    def test_detect_reports_missing_store(self):
        result = AuthAdapter("does-not-exist.json").detect()
        self.assertEqual(result.status, SessionStatus.MISSING)

    def test_loads_only_the_verified_synthetic_schema(self):
        path = self.copy_fixture("valid-session.json")
        result = AuthAdapter(path, adapter_version="synthetic-v1").load_session()
        self.assertEqual(result.status, SessionStatus.VALID)
        self.assertEqual(result.session.access_token, "SYNTHETIC_ACCESS_TOKEN_ONLY")
        self.assertNotEqual(result.fingerprint, result.session.access_token)

    def test_rejects_missing_token(self):
        path = self.copy_fixture("missing-token.json")
        result = AuthAdapter(path, adapter_version="synthetic-v1").load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)

    def test_rejects_malformed_json(self):
        path = self.copy_fixture("malformed.json")
        result = AuthAdapter(path, adapter_version="synthetic-v1").load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)

    def test_rejects_unknown_schema_version(self):
        path = self.copy_fixture("valid-session.json")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        payload["schema_version"] = 99
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        result = AuthAdapter(path, adapter_version="synthetic-v1").load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)

    def test_expired_session_requires_reauthentication(self):
        path = self.copy_fixture("valid-session.json")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        payload["expires_at"] = "2000-01-01T00:00:00Z"
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        result = AuthAdapter(path, adapter_version="synthetic-v1").load_session()
        self.assertEqual(result.status, SessionStatus.EXPIRED)
        self.assertEqual(AuthAdapter(path).refresh_if_needed(result).outcome, RefreshOutcome.REAUTH_REQUIRED)

    def test_refresh_outcomes_are_explicit(self):
        path = self.copy_fixture("valid-session.json")
        adapter = AuthAdapter(path, adapter_version="synthetic-v1")
        valid = adapter.load_session()
        self.assertEqual(adapter.refresh_if_needed(valid).outcome, RefreshOutcome.VALID)

        refreshed = AuthAdapter(path, refresh_callback=lambda _: valid.session, adapter_version="synthetic-v1").refresh_if_needed(
            type(valid)(SessionStatus.EXPIRED, "expired", valid.session, valid.fingerprint)
        )
        self.assertEqual(refreshed.outcome, RefreshOutcome.REFRESHED)

        self.assertEqual(adapter.refresh_if_needed(type(valid)(SessionStatus.EXPIRED, "expired", valid.session, valid.fingerprint)).outcome,
                         RefreshOutcome.REAUTH_REQUIRED)
        malformed = AuthAdapter(self.copy_fixture("malformed.json"), adapter_version="synthetic-v1").load_session()
        self.assertEqual(adapter.refresh_if_needed(malformed).outcome, RefreshOutcome.UNSUPPORTED)

    def test_fingerprint_changes_when_store_changes(self):
        path = self.copy_fixture("valid-session.json")
        adapter = AuthAdapter(path, adapter_version="synthetic-v1")
        first = adapter.load_session()
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("\n")
        second = adapter.load_session()
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_loads_real_codex_session_profile(self):
        path = self.copy_fixture("real-v1-session.json")
        result = AuthAdapter(path, adapter_version="real-v1").load_session()
        self.assertEqual(result.status, SessionStatus.VALID)
        self.assertTrue(result.fingerprint)
        self.assertEqual(
            result.session.access_token,
            "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJleHAiOjQxMDI0NDQ4MDB9.REAL_V1_SANITIZED_SIGNATURE",
        )
        self.assertFalse(hasattr(result.session, "refresh_token"))
        self.assertNotIn("REAL_V1_SANITIZED_REFRESH_TOKEN", repr(result.session))

    def test_real_profile_rejects_malformed_expiry_claim(self):
        path = self.copy_fixture("real-v1-session.json")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        payload["tokens"]["access_token"] = (
            "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0."
            "eyJleHAiOiJub3QtYS1udW1iZXJ9.REAL_V1_SANITIZED_SIGNATURE"
        )
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        result = AuthAdapter(path, adapter_version="real-v1").load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)

    def test_real_profile_applies_clock_skew_before_expiry(self):
        path = self.copy_fixture("real-v1-session.json")
        expiry = int(datetime.now(timezone.utc).timestamp()) + 30
        header = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0"
        body = base64.urlsafe_b64encode(
            json.dumps({"exp": expiry}, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        payload["tokens"]["access_token"] = "%s.%s.REAL_V1_SANITIZED_SIGNATURE" % (header, body)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        result = AuthAdapter(path, adapter_version="real-v1").load_session()
        self.assertEqual(result.status, SessionStatus.EXPIRED)

    def test_real_profile_does_not_invoke_refresh_callback(self):
        path = self.copy_fixture("real-v1-session.json")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        payload["tokens"]["access_token"] = (
            "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0."
            "eyJleHAiOjF9.REAL_V1_SANITIZED_SIGNATURE"
        )
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        called = []
        adapter = AuthAdapter(path, adapter_version="real-v1", refresh_callback=lambda _: called.append(True))
        loaded = adapter.load_session()
        refreshed = adapter.refresh_if_needed(loaded)
        self.assertEqual(refreshed.outcome, RefreshOutcome.REAUTH_REQUIRED)
        self.assertEqual(called, [])

    def test_environment_mode_requires_explicit_opt_in_and_expiry(self):
        fake_token = "env-token-not-a-jwt"
        with mock.patch.dict(os.environ, {"CODEX_ACCESS_TOKEN": fake_token}, clear=False):
            result = AuthAdapter("missing.json", adapter_version="real-v1").load_session()
        self.assertEqual(result.status, SessionStatus.MISSING)

        with mock.patch.dict(
            os.environ,
            {"CODEX_ROUTER_AUTH_MODE": "env", "CODEX_ACCESS_TOKEN": fake_token},
            clear=False,
        ):
            result = AuthAdapter("missing.json", adapter_version="real-v1").load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)

    def test_environment_mode_has_nonempty_fingerprint(self):
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_ROUTER_AUTH_MODE": "env",
                "CODEX_ACCESS_TOKEN": "env-token-not-a-jwt",
                "CODEX_ROUTER_TOKEN_EXPIRES_AT": "2100-01-01T00:00:00Z",
            },
            clear=False,
        ):
            result = AuthAdapter("missing.json", adapter_version="real-v1").load_session()
        self.assertEqual(result.status, SessionStatus.VALID)
        self.assertTrue(result.fingerprint)


class RedactionTests(unittest.TestCase):
    def test_redacts_bearer_and_token_shaped_values(self):
        message = "Authorization: Bearer abc123 access_token=secret-value"
        redacted = redact_text(message)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("secret-value", redacted)


if __name__ == "__main__":
    unittest.main()
