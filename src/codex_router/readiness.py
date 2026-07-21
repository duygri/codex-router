"""Bounded, secret-free Codex CLI and App Server readiness diagnostics."""

import math
import re
import subprocess
import threading
import time
from dataclasses import dataclass

from .app_server import AppServerBridge, AppServerError
from .config import ConfigError, RouterConfig, validate_router_config


VERSION_TIMEOUT_SECONDS = 2.0
APP_SERVER_TIMEOUT_SECONDS = 3.0
READINESS_CACHE_TTL_SECONDS = 10.0
READINESS_WAITER_TIMEOUT_SECONDS = 2.0
MAX_VERSION_OUTPUT_BYTES = 64 * 1024
CODEX_VERSION_RE = re.compile(r"\bcodex-cli\s+([0-9][A-Za-z0-9_.-]*)\b")

SAFE_CODES = {
    "ok",
    "skipped",
    "invalid_config",
    "codex_cli_not_found",
    "codex_cli_unavailable",
    "app_server_unavailable",
    "app_server_timeout",
    "app_server_protocol_error",
    "model_catalog_empty",
    "model_catalog_invalid",
    "model_catalog_unavailable",
    "readiness_wait_timeout",
    "diagnostic_failed",
}

_SKIPPED_SYNTHETIC = "Not required for synthetic-v1"
_SKIPPED_PREREQUISITE = "Not checked because a prerequisite failed"


class CheckResult:
    def __init__(self, ok, code, message, version=None, model_count=None):
        if code not in SAFE_CODES:
            raise ValueError("unsupported readiness code")
        if not isinstance(message, str) or not message:
            raise ValueError("readiness message must be text")
        if version is not None and not isinstance(version, str):
            raise ValueError("readiness version must be text")
        if model_count is not None and (isinstance(model_count, bool) or not isinstance(model_count, int) or model_count < 0):
            raise ValueError("readiness model count must be a non-negative integer")
        self.ok = ok
        self.code = code
        self.message = message
        self.version = version
        self.model_count = model_count

    @classmethod
    def ok(cls, message, version=None, model_count=None):
        return cls(True, "ok", message, version=version, model_count=model_count)

    @classmethod
    def failure(cls, code, message):
        return cls(False, code, message)

    @classmethod
    def skipped(cls, message):
        return cls(True, "skipped", message)

    def to_dict(self):
        value = {"ok": self.ok, "code": self.code, "message": self.message}
        if self.version is not None:
            value["version"] = self.version
        if self.model_count is not None:
            value["model_count"] = self.model_count
        return value


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    checks: dict

    def to_dict(self):
        return {
            "status": self.status,
            "checks": {name: result.to_dict() for name, result in self.checks.items()},
        }


def _skip_checks(message):
    return {
        "codex_cli": CheckResult.skipped(message),
        "app_server": CheckResult.skipped(message),
        "model_catalog": CheckResult.skipped(message),
    }


def _invalid_config_report(error):
    checks = {"config": CheckResult.failure("invalid_config", error.message)}
    checks.update(_skip_checks(_SKIPPED_PREREQUISITE))
    return ReadinessReport("invalid_config", checks)


def _not_ready_report(config_result, cli_result, app_result=None, model_result=None):
    checks = {"config": config_result, "codex_cli": cli_result}
    if app_result is None:
        app_result = CheckResult.skipped(_SKIPPED_PREREQUISITE)
    if model_result is None:
        model_result = CheckResult.skipped(_SKIPPED_PREREQUISITE)
    checks["app_server"] = app_result
    checks["model_catalog"] = model_result
    return ReadinessReport("not_ready", checks)


def _compute_report(config, cli_check, app_server_check):
    try:
        validate_router_config(config)
    except ConfigError as error:
        return _invalid_config_report(error)

    config_result = CheckResult.ok("Configuration is valid")
    if config.adapter_version == "synthetic-v1":
        checks = {"config": config_result}
        checks.update(_skip_checks(_SKIPPED_SYNTHETIC))
        return ReadinessReport("ready", checks)

    try:
        cli_result = cli_check()
    except Exception:
        cli_result = CheckResult.failure("diagnostic_failed", "Diagnostic check failed")
    if not cli_result.ok:
        return _not_ready_report(config_result, cli_result)

    try:
        app_result = app_server_check()
    except Exception:
        app_result = CheckResult.failure("diagnostic_failed", "Diagnostic check failed")
    if not app_result.ok:
        if app_result.code.startswith("model_catalog_"):
            return _not_ready_report(config_result, cli_result, CheckResult.ok("Codex App Server is available"), app_result)
        return _not_ready_report(config_result, cli_result, app_result)

    app_ok = CheckResult.ok("Codex App Server is available")
    model_ok = CheckResult.ok("Codex models are available", model_count=app_result.model_count or 0)
    return ReadinessReport("ready", {
        "config": config_result,
        "codex_cli": cli_result,
        "app_server": app_ok,
        "model_catalog": model_ok,
    })


def _default_cli_check(command):
    try:
        completed = subprocess.run(
            [command, "--version"],
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=VERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return CheckResult.failure("codex_cli_not_found", "Codex CLI was not found")
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return CheckResult.failure("codex_cli_unavailable", "Codex CLI is unavailable")
    output = completed.stdout or b""
    if len(output) > MAX_VERSION_OUTPUT_BYTES or completed.returncode != 0:
        return CheckResult.failure("codex_cli_unavailable", "Codex CLI is unavailable")
    try:
        text = output.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return CheckResult.failure("codex_cli_unavailable", "Codex CLI is unavailable")
    match = CODEX_VERSION_RE.search(text)
    if not match:
        return CheckResult.failure("codex_cli_unavailable", "Codex CLI version is unsupported")
    return CheckResult.ok("Codex CLI is available", version=match.group(1))


def _default_app_server_check(command):
    bridge = AppServerBridge(command=command, timeout=APP_SERVER_TIMEOUT_SECONDS)
    try:
        models = bridge.probe_models(timeout=APP_SERVER_TIMEOUT_SECONDS)
        return CheckResult.ok("Codex models are available", model_count=len(models))
    except AppServerError as error:
        mapping = {
            "app_server_timeout": "app_server_timeout",
            "app_server_protocol_error": "app_server_protocol_error",
            "model_catalog_empty": "model_catalog_empty",
            "model_catalog_invalid": "model_catalog_invalid",
        }
        code = mapping.get(error.code, "model_catalog_unavailable" if error.code.startswith("model_catalog") else "app_server_unavailable")
        message = {
            "app_server_timeout": "Codex App Server did not respond in time",
            "app_server_protocol_error": "Codex App Server returned an invalid response",
            "model_catalog_empty": "Codex returned no available models",
            "model_catalog_invalid": "Codex returned an invalid model catalog",
        }.get(code, "Codex App Server is unavailable")
        return CheckResult.failure(code, message)
    except Exception:
        return CheckResult.failure("diagnostic_failed", "Diagnostic check failed")
    finally:
        bridge.close()


class ReadinessProbe:
    def __init__(self, config, cli_check=None, app_server_check=None, clock=None, cache_ttl=READINESS_CACHE_TTL_SECONDS, waiter_timeout=READINESS_WAITER_TIMEOUT_SECONDS):
        self.config = config
        self.cli_check = cli_check or (lambda: _default_cli_check(config.codex_command))
        self.app_server_check = app_server_check or (lambda: _default_app_server_check(config.codex_command))
        self.clock = clock or time.monotonic
        self.cache_ttl = float(cache_ttl)
        self.waiter_timeout = float(waiter_timeout)
        self.condition = threading.Condition()
        self.running = False
        self.cached_report = None
        self.cached_at = None

    def _cache_valid(self, now):
        return self.cached_report is not None and self.cached_at is not None and now - self.cached_at < self.cache_ttl

    def _worker(self):
        try:
            report = _compute_report(self.config, self.cli_check, self.app_server_check)
        except Exception:
            report = ReadinessReport("not_ready", {
                "config": CheckResult.failure("diagnostic_failed", "Diagnostic check failed"),
                **_skip_checks(_SKIPPED_PREREQUISITE),
            })
        with self.condition:
            self.cached_report = report
            self.cached_at = self.clock()
            self.running = False
            self.condition.notify_all()

    def _waiter_timeout_report(self):
        try:
            validate_router_config(self.config)
            config_result = CheckResult.ok("Configuration is valid")
        except ConfigError as error:
            return _invalid_config_report(error)
        checks = {
            "config": config_result,
            "codex_cli": CheckResult.skipped(_SKIPPED_PREREQUISITE),
            "app_server": CheckResult.failure("readiness_wait_timeout", "Readiness probe is still running"),
            "model_catalog": CheckResult.skipped(_SKIPPED_PREREQUISITE),
        }
        return ReadinessReport("not_ready", checks)

    def check(self):
        with self.condition:
            now = self.clock()
            if self._cache_valid(now):
                return self.cached_report
            if not self.running:
                self.running = True
                threading.Thread(target=self._worker, daemon=True).start()
            deadline = time.monotonic() + self.waiter_timeout
            while self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._waiter_timeout_report()
                self.condition.wait(timeout=remaining)
            if self.cached_report is not None:
                return self.cached_report
            return self._waiter_timeout_report()


def doctor_report(config, cli_check=None, app_server_check=None):
    """Run an independent, uncached report for the CLI doctor command."""
    return _compute_report(
        config,
        cli_check or (lambda: _default_cli_check(config.codex_command)),
        app_server_check or (lambda: _default_app_server_check(config.codex_command)),
    )
