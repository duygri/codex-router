"""Secret-free aggregate request usage tracking."""

import json
import re
import threading
from datetime import datetime, timezone


_SAFE_MODEL = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_USAGE_KEY = "usage_aggregate"
_TERMINAL_STATES = {"completed", "failed", "cancelled"}


class UsageTrackerError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _empty_usage():
    return {
        "total_requests": 0,
        "completed_requests": 0,
        "failed_requests": 0,
        "cancelled_requests": 0,
        "active_requests": 0,
        "last_request_at": None,
        "by_model": {},
    }


class UsageHandle:
    def __init__(self, tracker, model):
        self.tracker = tracker
        self.model = model
        self.closed = False
        self.lock = threading.Lock()

    def complete(self, state):
        with self.lock:
            if self.closed:
                return False
            self.closed = True
        self.tracker.complete(self.model, state)
        return True


class UsageTracker:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.usage = self._load()

    def _load(self):
        raw = self.store.get(_USAGE_KEY)
        if raw is None:
            return _empty_usage()
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            raise UsageTrackerError(503, "usage_metadata_invalid", "Usage metadata is invalid")
        if not isinstance(value, dict):
            raise UsageTrackerError(503, "usage_metadata_invalid", "Usage metadata is invalid")
        result = _empty_usage()
        for key in result:
            if key == "by_model":
                continue
            candidate = value.get(key, result[key])
            if key == "last_request_at":
                if candidate is not None and (not isinstance(candidate, str) or not candidate.endswith("Z")):
                    raise UsageTrackerError(503, "usage_metadata_invalid", "Usage metadata is invalid")
            elif not isinstance(candidate, int) or candidate < 0:
                raise UsageTrackerError(503, "usage_metadata_invalid", "Usage metadata is invalid")
            result[key] = candidate
        by_model = value.get("by_model", {})
        if not isinstance(by_model, dict):
            raise UsageTrackerError(503, "usage_metadata_invalid", "Usage metadata is invalid")
        for model, count in by_model.items():
            if not isinstance(model, str) or not _SAFE_MODEL.fullmatch(model) or not isinstance(count, int) or count < 0:
                raise UsageTrackerError(503, "usage_metadata_invalid", "Usage metadata is invalid")
        result["by_model"] = dict(by_model)
        return result

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _persist_locked(self):
        self.store.set(_USAGE_KEY, json.dumps(self.usage, sort_keys=True, separators=(",", ":")))

    def begin(self, model):
        if not isinstance(model, str) or not _SAFE_MODEL.fullmatch(model):
            raise UsageTrackerError(400, "invalid_model", "Usage model identifier is invalid")
        with self.lock:
            self.usage["total_requests"] += 1
            self.usage["active_requests"] += 1
            self.usage["last_request_at"] = self._now()
            self.usage["by_model"][model] = self.usage["by_model"].get(model, 0) + 1
            self._persist_locked()
        return UsageHandle(self, model)

    def complete(self, model, state):
        if state not in _TERMINAL_STATES:
            raise UsageTrackerError(400, "invalid_usage_state", "Usage state is invalid")
        with self.lock:
            if self.usage["active_requests"] > 0:
                self.usage["active_requests"] -= 1
            self.usage[state + "_requests"] += 1
            self._persist_locked()

    def snapshot(self):
        with self.lock:
            result = {key: value for key, value in self.usage.items() if key != "by_model"}
            result["by_model"] = [
                {"model": model, "requests": count}
                for model, count in sorted(self.usage["by_model"].items())
            ]
            return result
