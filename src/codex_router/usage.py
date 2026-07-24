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
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
        "token_usage_available": False,
    }


class UsageHandle:
    def __init__(self, tracker, model):
        self.tracker = tracker
        self.model = model
        self.closed = False
        self.lock = threading.Lock()
        self.last_cumulative_tokens = None

    def complete(self, state):
        with self.lock:
            if self.closed:
                return False
            self.closed = True
        self.tracker.complete(self.model, state)
        return True

    def record_token_usage(self, usage):
        """Record only numeric token deltas; never retain the upstream payload."""
        with self.lock:
            if self.closed:
                return False
        parsed, cumulative = self.tracker.parse_token_usage(usage)
        if parsed is None:
            return False
        with self.lock:
            if cumulative and self.last_cumulative_tokens is not None:
                delta = {}
                for key, value in parsed.items():
                    previous = self.last_cumulative_tokens.get(key, 0)
                    delta[key] = value - previous if value >= previous else value
            else:
                delta = dict(parsed)
            if cumulative:
                self.last_cumulative_tokens = dict(parsed)
        self.tracker.add_token_delta(delta)
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
        if not isinstance(value.get("token_usage_available", result["token_usage_available"]), bool):
            raise UsageTrackerError(503, "usage_metadata_invalid", "Usage metadata is invalid")
        result["token_usage_available"] = value.get("token_usage_available", False)
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

    @staticmethod
    def parse_token_usage(usage):
        if not isinstance(usage, dict):
            return None, False
        cumulative = isinstance(usage.get("total"), dict)
        source = usage.get("total") if cumulative else usage
        if not isinstance(source, dict):
            return None, cumulative
        aliases = {
            "input_tokens": ("inputTokens", "input_tokens"),
            "cached_input_tokens": ("cachedInputTokens", "cached_input_tokens"),
            "output_tokens": ("outputTokens", "output_tokens"),
            "reasoning_output_tokens": ("reasoningOutputTokens", "reasoning_output_tokens"),
            "total_tokens": ("totalTokens", "total_tokens"),
        }
        parsed = {}
        for name, keys in aliases.items():
            value = next((source.get(key) for key in keys if key in source), 0)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return None, cumulative
            parsed[name] = value
        return parsed, cumulative

    def add_token_delta(self, delta):
        with self.lock:
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"):
                value = delta.get(key, 0)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    self.usage[key] += value
            self.usage["token_usage_available"] = True
            self._persist_locked()

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
