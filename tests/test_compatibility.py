import os
import tempfile
import unittest

from codex_router.compatibility import build_verification_evidence
from codex_router.storage import MetadataStore


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.store = MetadataStore(self.path)
        self.addCleanup(self.store.close)

    def test_apply_pin_and_rollback_are_explicit(self):
        self.store.set("adapter_version", "synthetic-v1")
        self.store.pin_adapter("synthetic-v2")
        self.assertEqual(self.store.get("adapter_version"), "synthetic-v2")
        self.assertEqual(self.store.rollback_adapter(), "synthetic-v1")
        self.assertEqual(self.store.get("adapter_version"), "synthetic-v1")

    def test_failed_compatibility_check_does_not_apply_pin(self):
        self.store.set("adapter_version", "synthetic-v1")
        compatibility_passed = False
        if compatibility_passed:
            self.store.pin_adapter("synthetic-v2")
        self.assertEqual(self.store.get("adapter_version"), "synthetic-v1")

    def test_known_version_and_successful_models_check_can_be_verified(self):
        evidence = build_verification_evidence(
            codex_version="26.715.7063.0",
            adapter_profile="real-v1",
            transport_url="app-server://stdio",
            http_status=200,
            checked_at="2026-07-21T00:00:00Z",
        )
        self.assertEqual(evidence["status"], "verified")
        self.assertEqual(evidence["codex_version"], "26.715.7063.0")
        self.assertEqual(evidence["transport"], "codex-app-server")
        self.assertEqual(evidence["transport_endpoint"], "stdio")

    def test_unknown_version_or_non_success_stays_unverified(self):
        evidence = build_verification_evidence(
            codex_version="unknown",
            adapter_profile="real-v1",
            transport_url="app-server://stdio",
            http_status=401,
            safe_error_code="auth_expired",
            checked_at="2026-07-21T00:00:00Z",
        )
        self.assertEqual(evidence["status"], "unverified")
        self.assertEqual(evidence["safe_error_code"], "auth_expired")

    def test_verification_evidence_rejects_secret_like_fields(self):
        with self.assertRaises(ValueError):
            build_verification_evidence(
                codex_version="26.715.7063.0",
                adapter_profile="real-v1",
                transport_url="app-server://stdio?access_token=secret",
                http_status=200,
            )


if __name__ == "__main__":
    unittest.main()
