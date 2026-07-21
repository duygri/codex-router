import json
import os
import tempfile
import threading
import unittest

from codex_router.storage import MetadataStore
from codex_router.usage import UsageTracker, UsageTrackerError


class UsageTrackerTests(unittest.TestCase):
    def make_tracker(self):
        handle, path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(handle)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        store = MetadataStore(path)
        self.addCleanup(store.close)
        return UsageTracker(store), store, path

    def test_tracks_terminal_lifecycle_once_and_keeps_only_aggregates(self):
        tracker, store, _ = self.make_tracker()
        request = tracker.begin("gpt-test")

        self.assertEqual(tracker.snapshot()["total_requests"], 1)
        self.assertEqual(tracker.snapshot()["active_requests"], 1)
        request.complete("completed")
        request.complete("failed")

        snapshot = tracker.snapshot()
        self.assertEqual(snapshot["completed_requests"], 1)
        self.assertEqual(snapshot["failed_requests"], 0)
        self.assertEqual(snapshot["active_requests"], 0)
        self.assertEqual(snapshot["by_model"], [{"model": "gpt-test", "requests": 1}])
        self.assertNotIn("prompt", store.get("usage_aggregate"))

    def test_tracks_failed_and_cancelled_requests(self):
        tracker, _, _ = self.make_tracker()
        failed = tracker.begin("gpt-test")
        cancelled = tracker.begin("gpt-test")
        failed.complete("failed")
        cancelled.complete("cancelled")

        snapshot = tracker.snapshot()
        self.assertEqual(snapshot["failed_requests"], 1)
        self.assertEqual(snapshot["cancelled_requests"], 1)
        self.assertEqual(snapshot["active_requests"], 0)

    def test_persists_aggregate_snapshot_across_tracker_restart(self):
        tracker, store, path = self.make_tracker()
        tracker.begin("gpt-test").complete("completed")
        store.close()

        reopened = MetadataStore(path)
        self.addCleanup(reopened.close)
        restored = UsageTracker(reopened)
        self.assertEqual(restored.snapshot()["completed_requests"], 1)
        json.loads(reopened.get("usage_aggregate"))

    def test_serializes_concurrent_updates(self):
        tracker, _, _ = self.make_tracker()

        def work():
            tracker.begin("gpt-test").complete("completed")

        threads = [threading.Thread(target=work) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = tracker.snapshot()
        self.assertEqual(snapshot["total_requests"], 12)
        self.assertEqual(snapshot["completed_requests"], 12)
        self.assertEqual(snapshot["active_requests"], 0)

    def test_rejects_unsafe_model_identifier(self):
        tracker, _, _ = self.make_tracker()
        with self.assertRaises(UsageTrackerError):
            tracker.begin("prompt\ncontent")


if __name__ == "__main__":
    unittest.main()
