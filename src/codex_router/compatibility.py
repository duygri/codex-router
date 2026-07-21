"""Maintainer-side, secret-free compatibility evidence helpers."""

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:-]+$")


def _safe_identifier(value, name):
    if not isinstance(value, str) or not value or not _SAFE_VALUE.fullmatch(value):
        raise ValueError("%s is invalid" % name)
    return value


def build_verification_evidence(
    codex_version,
    adapter_profile,
    transport_url,
    http_status,
    safe_error_code=None,
    checked_at=None,
):
    version = _safe_identifier(codex_version, "codex_version")
    profile = _safe_identifier(adapter_profile, "adapter_profile")
    parsed = urlsplit(transport_url)
    if (
        parsed.scheme != "app-server"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.hostname != "stdio"
        or parsed.path not in ("", "/")
    ):
        raise ValueError("transport_url is unsafe")
    if not isinstance(http_status, int) or not 100 <= http_status <= 599:
        raise ValueError("http_status is invalid")
    if safe_error_code is not None:
        safe_error_code = _safe_identifier(safe_error_code, "safe_error_code")
    timestamp = checked_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _parse_checked_at(timestamp)
    verified = version != "unknown" and 200 <= http_status < 300
    return {
        "status": "verified" if verified else "unverified",
        "codex_version": version,
        "adapter_profile": profile,
        "transport": "codex-app-server",
        "transport_endpoint": "stdio",
        "http_status": http_status,
        "safe_error_code": safe_error_code,
        "checked_at": timestamp,
    }


def _parse_checked_at(value):
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise ValueError("checked_at is invalid")


def write_verification_evidence(path, evidence):
    """Write reviewed evidence atomically; never accept or write secrets."""
    if not isinstance(evidence, dict) or set(evidence) != {
        "status",
        "codex_version",
        "adapter_profile",
        "transport",
        "transport_endpoint",
        "http_status",
        "safe_error_code",
        "checked_at",
    }:
        raise ValueError("verification evidence shape is invalid")
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(evidence, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)
