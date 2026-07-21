"""Environment-backed configuration with loopback-safe defaults."""

import os
import math
import re
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when router configuration cannot be used safely."""

    def __init__(self, message, code="invalid_config"):
        super().__init__(message)
        self.code = code
        self.message = message


try:
    from .model_catalog import is_safe_model_id as _catalog_is_safe_model_id
except ImportError:
    _catalog_is_safe_model_id = None


_JWT_SHAPED_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_TOKEN_PREFIX_RE = re.compile(r"^(?:bearer|sk-|access[_-]?token|refresh[_-]?token)", re.IGNORECASE)


def is_safe_model_id(value):
    """Apply the shared model-ID contract plus configuration-only safety checks."""
    if not isinstance(value, str) or not value or len(value) > 256:
        return False
    if any(character.isspace() for character in value):
        return False
    if _JWT_SHAPED_RE.fullmatch(value) or _TOKEN_PREFIX_RE.match(value):
        return False
    if _catalog_is_safe_model_id is not None and not _catalog_is_safe_model_id(value):
        return False
    return "\n" not in value and "\r" not in value


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _parse_fallbacks(value):
    if value is None or value == "":
        return ()
    return tuple(value.split(","))


def _parse_start_timeout(value):
    parsed = _parse_float(value)
    if isinstance(parsed, (int, float)) and not isinstance(parsed, bool) and math.isfinite(parsed) and 1 <= parsed <= 5:
        return parsed
    return value


def validate_router_config(config, host=None, port=None):
    """Validate settings used before constructing stores, servers, or gateways."""
    if getattr(config, "config_error", ""):
        raise ConfigError("Router configuration is invalid")

    effective_host = config.bind_host if host is None else host
    effective_port = config.port if port is None else port
    if not isinstance(effective_host, str) or effective_host.lower().rstrip(".") not in ("127.0.0.1", "localhost", "::1"):
        raise ConfigError("Router configuration is invalid")
    if isinstance(effective_port, bool) or not isinstance(effective_port, int) or not 1 <= effective_port <= 65535:
        raise ConfigError("Router configuration is invalid")
    if config.browser_policy not in ("auto", "always", "never"):
        raise ConfigError("Router configuration is invalid")
    if (
        isinstance(config.start_timeout, bool)
        or not isinstance(config.start_timeout, (int, float))
        or not math.isfinite(config.start_timeout)
        or not 1 <= config.start_timeout <= 5
    ):
        raise ConfigError("Router configuration is invalid")
    fallbacks = config.model_fallbacks
    if not isinstance(fallbacks, (tuple, list)) or len(fallbacks) > 8:
        raise ConfigError("Router configuration is invalid")
    if any(not is_safe_model_id(value) for value in fallbacks):
        raise ConfigError("Router configuration is invalid")
    return effective_host, effective_port


@dataclass
class RouterConfig:
    bind_host: str = "127.0.0.1"
    port: int = 20128
    auth_path: str = ""
    upstream_url: str = ""
    database_path: str = ""
    adapter_version: str = "synthetic-v1"
    browser_policy: str = "auto"
    start_timeout: object = 5.0
    model_fallbacks: tuple = ()

    @classmethod
    def from_env(cls):
        home = os.path.expanduser("~")
        default_db_dir = os.path.join(home, ".codex-router")
        return cls(
            bind_host=os.environ.get("CODEX_ROUTER_HOST", "127.0.0.1"),
            port=_parse_int(os.environ.get("CODEX_ROUTER_PORT", "20128")),
            auth_path=os.environ.get("CODEX_ROUTER_AUTH_FILE", os.path.join(home, ".codex", "auth.json")),
            upstream_url=os.environ.get("CODEX_ROUTER_UPSTREAM_URL", ""),
            database_path=os.environ.get("CODEX_ROUTER_DATABASE", os.path.join(default_db_dir, "router.sqlite3")),
            adapter_version=os.environ.get("CODEX_ROUTER_ADAPTER", "synthetic-v1"),
            browser_policy=os.environ.get("CODEX_ROUTER_BROWSER", "auto"),
            start_timeout=_parse_start_timeout(os.environ.get("CODEX_ROUTER_START_TIMEOUT", "5")),
            model_fallbacks=_parse_fallbacks(os.environ.get("CODEX_ROUTER_MODEL_FALLBACKS")),
        )
