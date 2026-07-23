import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

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
        result = AuthAdapter(path).load_session()
        self.assertEqual(result.status, SessionStatus.VALID)
        self.assertEqual(result.session.access_token, "SYNTHETIC_ACCESS_TOKEN_ONLY")
        self.assertNotEqual(result.fingerprint, result.session.access_token)

    def test_rejects_missing_token(self):
        path = self.copy_fixture("missing-token.json")
        result = AuthAdapter(path).load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)

    def test_rejects_malformed_json(self):
        path = self.copy_fixture("malformed.json")
        result = AuthAdapter(path).load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)

    def test_rejects_unknown_schema_version(self):
        path = self.copy_fixture("valid-session.json")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        payload["schema_version"] = 99
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        result = AuthAdapter(path).load_session()
        self.assertEqual(result.status, SessionStatus.UNSUPPORTED)

    def test_expired_session_requires_reauthentication(self):
        path = self.copy_fixture("valid-session.json")
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        payload["expires_at"] = "2000-01-01T00:00:00Z"
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        result = AuthAdapter(path).load_session()
        self.assertEqual(result.status, SessionStatus.EXPIRED)
        self.assertEqual(AuthAdapter(path).refresh_if_needed(result).outcome, RefreshOutcome.REAUTH_REQUIRED)

    def test_refresh_outcomes_are_explicit(self):
        path = self.copy_fixture("valid-session.json")
        adapter = AuthAdapter(path)
        valid = adapter.load_session()
        self.assertEqual(adapter.refresh_if_needed(valid).outcome, RefreshOutcome.VALID)

        refreshed = AuthAdapter(path, refresh_callback=lambda _: valid.session).refresh_if_needed(
            type(valid)(SessionStatus.EXPIRED, "expired", valid.session, valid.fingerprint)
        )
        self.assertEqual(refreshed.outcome, RefreshOutcome.REFRESHED)

        self.assertEqual(adapter.refresh_if_needed(type(valid)(SessionStatus.EXPIRED, "expired", valid.session, valid.fingerprint)).outcome,
                         RefreshOutcome.REAUTH_REQUIRED)
        malformed = AuthAdapter(self.copy_fixture("malformed.json")).load_session()
        self.assertEqual(adapter.refresh_if_needed(malformed).outcome, RefreshOutcome.UNSUPPORTED)

    def test_fingerprint_changes_when_store_changes(self):
        path = self.copy_fixture("valid-session.json")
        adapter = AuthAdapter(path)
        first = adapter.load_session()
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("\n")
        second = adapter.load_session()
        self.assertNotEqual(first.fingerprint, second.fingerprint)


class RedactionTests(unittest.TestCase):
    def test_redacts_bearer_and_token_shaped_values(self):
        message = "Authorization: Bearer abc123 access_token=secret-value"
        redacted = redact_text(message)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("secret-value", redacted)


if __name__ == "__main__":
    unittest.main()
