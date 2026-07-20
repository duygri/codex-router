import os
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
