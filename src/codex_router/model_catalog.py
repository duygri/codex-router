"""Validated Codex model catalog with a short-lived stale-safe cache."""

import threading
import time


class ModelCatalogError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def is_safe_model_id(value):
    return isinstance(value, str) and bool(value) and len(value) <= 256 and "\n" not in value and "\r" not in value


class ModelCatalog:
    def __init__(self, fetch_models, ttl_seconds=60, clock=None):
        self.fetch_models = fetch_models
        self.ttl_seconds = max(0, float(ttl_seconds))
        self.clock = clock or time.monotonic
        self.lock = threading.RLock()
        self._models = None
        self._resolved_ids = []
        self._refreshed_at = 0.0
        self.stale = False

    def _normalize(self, raw_models):
        if not isinstance(raw_models, list):
            raise ModelCatalogError(502, "model_catalog_protocol_error", "Codex returned an invalid model catalog")
        normalized = []
        seen = set()
        for item in raw_models:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id") or item.get("model")
            if not is_safe_model_id(model_id):
                continue
            if model_id in seen:
                continue
            seen.add(model_id)
            normalized.append({
                "id": model_id,
                "alias": None,
                "owned_by": "codex",
                "available": True,
            })
        if not normalized:
            raise ModelCatalogError(503, "model_catalog_empty", "Codex returned no available models")
        resolved_ids = [item["id"] for item in normalized]
        if "codex" not in seen:
            normalized.insert(0, {
                "id": "codex",
                "alias": "codex",
                "owned_by": "codex-router",
                "available": True,
            })
        return normalized, resolved_ids

    def _refresh_if_needed(self):
        now = self.clock()
        if self._models is not None and now - self._refreshed_at < self.ttl_seconds:
            return
        try:
            models, resolved_ids = self._normalize(self.fetch_models())
        except ModelCatalogError:
            if self._models is None:
                raise
            self.stale = True
            return
        except Exception:
            if self._models is None:
                raise ModelCatalogError(503, "model_catalog_unavailable", "Codex model catalog is unavailable")
            self.stale = True
            return
        self._models = models
        self._resolved_ids = resolved_ids
        self._refreshed_at = now
        self.stale = False

    def list_models(self):
        with self.lock:
            self._refresh_if_needed()
            return [dict(item) for item in self._models]

    def resolve(self, model=None):
        with self.lock:
            self._refresh_if_needed()
            requested = "codex" if model is None else model
            if not is_safe_model_id(requested):
                raise ModelCatalogError(400, "invalid_model", "model must be a short text value")
            if requested == "codex" and "codex" not in self._resolved_ids:
                return self._resolved_ids[0]
            if requested in self._resolved_ids:
                return requested
            raise ModelCatalogError(400, "unknown_model", "Requested model is not available")

    def resolve_candidates(self, model=None, fallback_models=()):
        """Return a primary model and only configured, currently live fallbacks."""
        with self.lock:
            primary = self.resolve(model)
            candidates = [primary]
            if model not in (None, "codex"):
                return candidates
            for candidate in fallback_models or ():
                if not is_safe_model_id(candidate):
                    continue
                if candidate in self._resolved_ids and candidate not in candidates:
                    candidates.append(candidate)
            return candidates
