"""SQLite metadata store; raw credentials are intentionally not supported."""

import re
import sqlite3
import threading


_SECRET_KEY_RE = re.compile(r"(?:token|secret|password|api[_-]?key|authorization)", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bBearer\s+\S+", re.IGNORECASE)


class MetadataStore:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        with self.lock:
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self.connection.commit()

    def close(self):
        with self.lock:
            self.connection.close()

    def _assert_safe(self, key, value):
        if _SECRET_KEY_RE.search(str(key)) or _BEARER_RE.search(str(value)):
            raise ValueError("secret-like metadata is not allowed")

    def set(self, key, value):
        self._assert_safe(key, value)
        with self.lock:
            self.connection.execute(
                "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(key), str(value)),
            )
            self.connection.commit()

    def get(self, key):
        with self.lock:
            row = self.connection.execute("SELECT value FROM metadata WHERE key = ?", (str(key),)).fetchone()
        return None if row is None else row[0]

    def snapshot(self):
        with self.lock:
            rows = self.connection.execute("SELECT key, value FROM metadata ORDER BY key").fetchall()
        return dict(rows)

    def pin_adapter(self, version):
        current = self.get("adapter_version")
        if current:
            self.set("adapter_previous", current)
        self.set("adapter_version", version)

    def rollback_adapter(self):
        previous = self.get("adapter_previous")
        if previous is None:
            return None
        current = self.get("adapter_version")
        self.set("adapter_version", previous)
        if current:
            self.set("adapter_previous", current)
        return previous

    def reset(self):
        with self.lock:
            self.connection.execute("DELETE FROM metadata")
            self.connection.commit()
