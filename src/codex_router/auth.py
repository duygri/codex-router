"""Fail-closed Codex session adapters.

The real-v1 request transport is Codex App Server. This adapter remains for
safe local health/status reporting and never supplies bearer credentials to
that transport. The synthetic-v1 profile remains available only for
deterministic local tests.
"""

import base64
import hashlib
import json
import math
import os
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


CLOCK_SKEW_SECONDS = 60


class SessionStatus(Enum):
        VALID = "valid"
        EXPIRED = "expired"
        MISSING = "missing"
        UNSUPPORTED = "unsupported"


class RefreshOutcome(Enum):
        VALID = "valid"
        REFRESHED = "refreshed"
        REAUTH_REQUIRED = "reauth_required"
        UNSUPPORTED = "unsupported"


@dataclass
class Session:
        access_token: str
        expires_at: datetime


@dataclass
class LoadResult:
        status: SessionStatus
        message: str
        session: object = None
        fingerprint: str = ""


@dataclass
class RefreshResult:
        outcome: RefreshOutcome
        message: str
        session: object = None


def fingerprint_bytes(data):
        return hashlib.sha256(data).hexdigest()


def _parse_expiry(value):
        if not isinstance(value, str):
                    raise ValueError("expires_at must be an ISO-8601 string")
                normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)



def _decode_jwt_expiry(token):
        parts = token.split(".")
    if len(parts) != 3 or not all(parts):
                raise ValueError("token is not JWT-shaped")
            encoded = parts[1] + ("=" * (-len(parts[1]) % 4))
    try:
                payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8"))
except (UnicodeEncodeError, UnicodeDecodeError, ValueError, TypeError):
        raise ValueError("token payload is invalid")
    expiry = payload.get("exp") if isinstance(payload, dict) else None
    if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
                raise ValueError("token expiry claim is invalid")
            if not math.isfinite(float(expiry)) or expiry <= 0:
                        raise ValueError("token expiry claim is invalid")
                    return datetime.fromtimestamp(float(expiry), timezone.utc)


def _identity(stat_result):
        return (getattr(stat_result, "st_dev", None), getattr(stat_result, "st_ino", None), stat_result.st_size, stat_result.st_mtime_ns)


class AuthAdapter:
        """Read a verified local session profile and never write credentials."""

    def __init__(
                self,
                path,
                refresh_callback=None,
                adapter_version="real-v1",
                auth_mode=None,
                now=None,
    ):
                self.path = os.fspath(path)
                self.refresh_callback = refresh_callback
                self.adapter_version = adapter_version
                self.auth_mode = auth_mode or os.environ.get("CODEX_ROUTER_AUTH_MODE", "file")
                self.now = now or (lambda: datetime.now(timezone.utc))

    def detect(self):
                if self.adapter_version not in ("real-v1", "synthetic-v1"):
                                return LoadResult(SessionStatus.UNSUPPORTED, "Codex adapter version is not supported")
                            if self.adapter_version == "real-v1":
                                            return LoadResult(
                                                                SessionStatus.UNSUPPORTED,
                                                                "Real Codex account status is provided by Codex App Server",
                                            )
                                        if self.auth_mode == "env":
                                                        if os.environ.get("CODEX_ACCESS_TOKEN"):
                                                                            return LoadResult(SessionStatus.VALID, "Codex environment token detected")
                                                                        return LoadResult(SessionStatus.MISSING, "CODEX_ACCESS_TOKEN is not set")
        if not os.path.isfile(self.path):
                        return LoadResult(SessionStatus.MISSING, "Codex session file was not found")
        return LoadResult(SessionStatus.VALID, "Codex session file detected")

    def _validate_file_stat(self, stat_result):
                if not stat.S_ISREG(stat_result.st_mode):
                                raise OSError("Codex session file is not a regular file")
        attributes = getattr(stat_result, "st_file_attributes", 0)
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if attributes & reparse_point:
                        raise OSError("Codex session file uses a reparse point")
        if os.name != "nt":
            mode = stat.S_IMODE(stat_result.st_mode)
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                                raise OSError("Codex session file permissions are too broad")


    def _validate_windows_acl(self):
                if os.name != "nt":
                                return
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        icacls = os.path.join(system_root, "System32", "icacls.exe")
        try:
                        result = subprocess.run(
                                            [icacls, self.path],
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE,
                                            timeout=2,
                                            check=False,
                                            universal_newlines=True,
                        )
except (OSError, subprocess.SubprocessError):
            raise OSError("Codex session ACL could not be verified")
        if result.returncode != 0:
                        raise OSError("Codex session ACL could not be verified")
        output = (result.stdout or "") + (result.stderr or "")
        broad_principals = (
                        "Everyone:",
                        "BUILTIN\\Users:",
                        "NT AUTHORITY\\Authenticated Users:",
                        "NT AUTHORITY\\ANONYMOUS LOGON:",
        )
        if any(principal.lower() in output.lower() for principal in broad_principals):
                        raise OSError("Codex session ACL grants broad access")

    def _read_stable(self):
                for _ in range(2):
                                fd = None
            try:
                                before_stat = os.stat(self.path, follow_symlinks=False)
                if os.path.islink(self.path):
                                        raise OSError("Codex session file is a symbolic link")
                self._validate_file_stat(before_stat)
                self._validate_windows_acl()
                flags = os.O_RDONLY
                flags |= getattr(os, "O_BINARY", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(self.path, flags)
                opened_stat = os.fstat(fd)
                self._validate_file_stat(opened_stat)
                if _identity(before_stat) != _identity(opened_stat):
                                        raise OSError("Codex session file changed while opening")
                chunks = []
                while True:
                                        chunk = os.read(fd, 65536)
                    if not chunk:
                                                break
                    chunks.append(chunk)
                data = b"".join(chunks)
except (OSError, IOError) as exc:
                return None, "Unable to read Codex session file: %s" % type(exc).__name__
finally:
                if fd is not None:
                                        os.close(fd)
            try:
                                after_stat = os.stat(self.path, follow_symlinks=False)
except (OSError, IOError):
                return None, "Codex session file disappeared while being read"
            if _identity(before_stat) == _identity(after_stat):
                                return data, fingerprint_bytes(data)
        return None, "Codex session changed while it was being read"

    def _load_environment_session(self):
                token = os.environ.get("CODEX_ACCESS_TOKEN")
        if not token:
                        return LoadResult(SessionStatus.MISSING, "CODEX_ACCESS_TOKEN is not set")
        try:
                        if len(token.split(".")) == 3:
                                            expires_at = _decode_jwt_expiry(token)
else:
                configured = os.environ.get("CODEX_ROUTER_TOKEN_EXPIRES_AT")
                if not configured:
                                        return LoadResult(SessionStatus.UNSUPPORTED, "Environment token expiry is not configured")
                expires_at = _parse_expiry(configured)
except (ValueError, OverflowError, OSError):
            return LoadResult(SessionStatus.UNSUPPORTED, "Environment token expiry is invalid")
        fingerprint = fingerprint_bytes(b"codex-router-env-token\0" + token.encode("utf-8"))
        session = Session(token, expires_at)
        if expires_at <= self.now() + timedelta(seconds=CLOCK_SKEW_SECONDS):
                        return LoadResult(SessionStatus.EXPIRED, "Codex environment token has expired", session, fingerprint)
        return LoadResult(SessionStatus.VALID, "Codex environment token is valid", session, fingerprint)

    def load_session(self):
                if self.adapter_version not in ("real-v1", "synthetic-v1"):
                                return LoadResult(SessionStatus.UNSUPPORTED, "Codex session schema is not verified")

        if self.adapter_version == "real-v1":
                        return LoadResult(
                                            SessionStatus.UNSUPPORTED,
                                            "Real Codex account status is provided by Codex App Server",
                        )

        if self.auth_mode == "env":
                        return self._load_environment_session()
        if not os.path.isfile(self.path):
                        return LoadResult(SessionStatus.MISSING, "Codex session file was not found")

        data, fingerprint_or_error = self._read_stable()
        if data is None:
                        return LoadResult(SessionStatus.UNSUPPORTED, fingerprint_or_error)
        fingerprint = fingerprint_or_error
        try:
                        payload = json.loads(data.decode("utf-8"))
except (UnicodeDecodeError, ValueError):
            return LoadResult(SessionStatus.UNSUPPORTED, "Codex session is not valid JSON", fingerprint=fingerprint)

        if self.adapter_version == "synthetic-v1":
                        return self._load_synthetic(payload, fingerprint)

    def _load_synthetic(self, payload, fingerprint):
                if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                                return LoadResult(SessionStatus.UNSUPPORTED, "Codex session schema is not verified", fingerprint=fingerprint)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
                        return LoadResult(SessionStatus.UNSUPPORTED, "Codex session has no verified access token", fingerprint=fingerprint)
        try:
                        expires_at = _parse_expiry(payload.get("expires_at"))
except (TypeError, ValueError):
            return LoadResult(SessionStatus.UNSUPPORTED, "Codex session expiry is invalid", fingerprint=fingerprint)
        session = Session(token, expires_at)
        if expires_at <= self.now():
                        return LoadResult(SessionStatus.EXPIRED, "Codex session has expired", session, fingerprint)
        return LoadResult(SessionStatus.VALID, "Codex session is valid", session, fingerprint)

    def refresh_if_needed(self, result):
                if result.status == SessionStatus.VALID:
                                return RefreshResult(RefreshOutcome.VALID, "Codex session is valid", result.session)
        if result.status != SessionStatus.EXPIRED:
                        return RefreshResult(RefreshOutcome.UNSUPPORTED, "Codex session cannot be refreshed safely")
        if self.adapter_version == "real-v1":
                        return RefreshResult(RefreshOutcome.REAUTH_REQUIRED, "Run codex login to reauthenticate")
        if self.refresh_callback is None:
                        return RefreshResult(RefreshOutcome.REAUTH_REQUIRED, "Run codex login to reauthenticate")
        try:
                        refreshed_session = self.refresh_callback(result.session)
except Exception:
            return RefreshResult(RefreshOutcome.UNSUPPORTED, "Codex refresh contract failed")
        if not isinstance(refreshed_session, Session):
                        return RefreshResult(RefreshOutcome.UNSUPPORTED, "Codex refresh contract returned an invalid session")
        return RefreshResult(RefreshOutcome.REFRESHED, "Codex session was refreshed", refreshed_session)

    def health_check(self):
                return self.load_session()

    def current_fingerprint(self):
                if self.adapter_version == "real-v1":
                                return ""
        if self.auth_mode == "env":
                        loaded = self._load_environment_session()
            return loaded.fingerprint
        if not os.path.isfile(self.path):
                        return ""
        data, fingerprint_or_error = self._read_stable()
        return "" if data is None else fingerprint_or_error
