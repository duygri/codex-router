import os
import tempfile
import unittest

from codex_router.storage import MetadataStore


class MetadataStoreTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.store = MetadataStore(self.path)
        self.addCleanup(self.store.close)

    def test_creates_schema_and_persists_non_secret_status(self):
        self.store.set("codex_version", "unknown")
        self.store.set("health_status", "missing")
        self.assertEqual(self.store.get("health_status"), "missing")

    def test_rejects_secret_like_values(self):
        with self.assertRaises(ValueError):
            self.store.set("access_token", "SYNTHETIC_ACCESS_TOKEN_ONLY")
        with self.assertRaises(ValueError):
            self.store.set("health_status", "Authorization: Bearer secret")

    def test_pin_and_rollback_adapter(self):
        self.store.set("adapter_version", "synthetic-v1")
        self.store.pin_adapter("synthetic-v2")
        self.assertEqual(self.store.get("adapter_version"), "synthetic-v2")
        self.assertEqual(self.store.get("adapter_previous"), "synthetic-v1")
        self.assertEqual(self.store.rollback_adapter(), "synthetic-v1")
        self.assertEqual(self.store.get("adapter_version"), "synthetic-v1")

    def test_reset_clears_router_state(self):
        self.store.set("health_status", "valid")
        self.store.set("adapter_version", "synthetic-v1")
        self.store.reset()
        self.assertIsNone(self.store.get("health_status"))
        self.assertIsNone(self.store.get("adapter_version"))


if __name__ == "__main__":
    unittest.main()
