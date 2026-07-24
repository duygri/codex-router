"""Environment-backed configuration with loopback-safe defaults."""

import json
import os
import re
import secrets
import stat
import tempfile
import math
from dataclasses import dataclass


_ROUTER_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class ConfigError(Exception):
    def __init__(self, message, code="invalid_config"):
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_private_file(path):
    if os.path.islink(path):
        raise ConfigError("router config is invalid")
    try:
        result = os.stat(path, follow_symlinks=False)
    except OSError:
        raise ConfigError("router config is invalid")
    if not stat.S_ISREG(result.st_mode):
        raise ConfigError("router config is invalid")
    attributes = getattr(result, "st_file_attributes", 0)
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse_point:
        raise ConfigError("router config is invalid")
    if os.name != "nt" and stat.S_IMODE(result.st_mode) & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError("router config is invalid")


def _read_router_key(path):
    if not os.path.exists(path):
        return "", ""
    try:
        _validate_private_file(path)
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream)
        key = value.get("router_api_key") if isinstance(value, dict) else None
        if not isinstance(key, str) or not _ROUTER_KEY_RE.fullmatch(key):
            raise ConfigError("router config is invalid")
        return key, ""
    except (OSError, ValueError, TypeError, ConfigError):
        return "", "router config is invalid"


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


def validate_router_config(config, host=None, port=None, require_router_key=True):
    effective_host = config.bind_host if host is None else host
    effective_port = config.port if port is None else port
    if config.adapter_version not in ("real-v1", "synthetic-v1"):
        raise ConfigError("Supported adapters are real-v1 and synthetic-v1")
    if (effective_host or "").lower().rstrip(".") not in ("127.0.0.1", "localhost", "::1"):
        raise ConfigError("Codex Router only supports loopback binds")
    if isinstance(effective_port, bool) or not isinstance(effective_port, int) or not 1 <= effective_port <= 65535:
        raise ConfigError("Router port must be an integer from 1 to 65535")
    if isinstance(config.queue_size, bool) or not isinstance(config.queue_size, int) or config.queue_size < 0:
        raise ConfigError("Router queue size must be a non-negative integer")
    if isinstance(config.queue_timeout, bool) or not isinstance(config.queue_timeout, (int, float)) or not math.isfinite(config.queue_timeout) or config.queue_timeout < 0.1:
        raise ConfigError("Router queue timeout must be finite and at least 0.1 seconds")
    if require_router_key and not config.router_api_key:
        raise ConfigError("Router key is not configured; run codex-router init first.")
    return effective_host, effective_port


def initialize_router_config(path):
    """Create a local router config once and return its key without printing it."""
    path = os.fspath(path)
    if os.path.lexists(path):
        key, error = _read_router_key(path)
        if error:
            raise ConfigError(error)
        return key
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, mode=0o700, exist_ok=True)
    key = secrets.token_urlsafe(32)
    temp_path = ""
    fd = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".router-config-", dir=parent, text=True)
        os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            json.dump({"router_api_key": key}, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        temp_path = ""
        _validate_private_file(path)
        return key
    except (OSError, ValueError, ConfigError) as error:
        raise ConfigError("router config could not be initialized") from error
    finally:
        if fd is not None:
            os.close(fd)
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@dataclass
class RouterConfig:
    bind_host: str = "127.0.0.1"
    port: int = 20128
    auth_path: str = ""
    upstream_url: str = ""
    database_path: str = ""
    adapter_version: str = "real-v1"
    router_api_key: str = ""
    auth_mode: str = "file"
    token_expires_at: str = ""
    codex_command: str = "codex"
    config_path: str = ""
    config_error: str = ""
    queue_size: int = 2
    queue_timeout: float = 30.0
    model_fallbacks: tuple = ()

    @classmethod
    def from_env(cls):
        home = os.path.expanduser("~")
        codex_home = os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
        default_db_dir = os.path.join(home, ".codex-router")
        explicit_auth_path = os.environ.get("CODEX_ROUTER_AUTH_FILE")
        auth_path = explicit_auth_path or os.path.join(codex_home, "auth.json")
        config_path = os.environ.get("CODEX_ROUTER_CONFIG", os.path.join(default_db_dir, "config.json"))
        router_api_key = os.environ.get("CODEX_ROUTER_API_KEY", "")
        config_error = ""
        if router_api_key and not _ROUTER_KEY_RE.fullmatch(router_api_key):
            router_api_key = ""
            config_error = "router api key is invalid"
        elif not router_api_key:
            router_api_key, config_error = _read_router_key(config_path)
        port = _parse_int(os.environ.get("CODEX_ROUTER_PORT", "20128"))
        queue_size = _parse_int(os.environ.get("CODEX_ROUTER_QUEUE_SIZE", "2"))
        queue_timeout = _parse_float(os.environ.get("CODEX_ROUTER_QUEUE_TIMEOUT", "30"))
        fallback_values = tuple(
            value.strip() for value in os.environ.get("CODEX_ROUTER_MODEL_FALLBACKS", "").split(",")
            if value.strip()
        )
        return cls(
            bind_host=os.environ.get("CODEX_ROUTER_HOST", "127.0.0.1"),
            port=port,
            auth_path=auth_path,
            upstream_url=os.environ.get("CODEX_ROUTER_UPSTREAM_URL", "https://api.openai.com/v1"),
            database_path=os.environ.get("CODEX_ROUTER_DATABASE", os.path.join(default_db_dir, "router.sqlite3")),
            adapter_version=os.environ.get("CODEX_ROUTER_ADAPTER", "real-v1"),
            router_api_key=router_api_key,
            auth_mode=os.environ.get("CODEX_ROUTER_AUTH_MODE", "file"),
            token_expires_at=os.environ.get("CODEX_ROUTER_TOKEN_EXPIRES_AT", ""),
            codex_command=os.environ.get("CODEX_ROUTER_CODEX_COMMAND", "codex"),
            config_path=config_path,
            config_error=config_error,
            queue_size=queue_size,
            queue_timeout=queue_timeout,
            model_fallbacks=fallback_values,
        )
