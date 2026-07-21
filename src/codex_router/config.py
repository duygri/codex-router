"""Environment-backed configuration with loopback-safe defaults."""

import os
from dataclasses import dataclass


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

    @classmethod
    def from_env(cls):
        home = os.path.expanduser("~")
        codex_home = os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
        default_db_dir = os.path.join(home, ".codex-router")
        explicit_auth_path = os.environ.get("CODEX_ROUTER_AUTH_FILE")
        auth_path = explicit_auth_path or os.path.join(codex_home, "auth.json")
        return cls(
            bind_host=os.environ.get("CODEX_ROUTER_HOST", "127.0.0.1"),
            port=int(os.environ.get("CODEX_ROUTER_PORT", "20128")),
            auth_path=auth_path,
            upstream_url=os.environ.get("CODEX_ROUTER_UPSTREAM_URL", "https://api.openai.com/v1"),
            database_path=os.environ.get("CODEX_ROUTER_DATABASE", os.path.join(default_db_dir, "router.sqlite3")),
            adapter_version=os.environ.get("CODEX_ROUTER_ADAPTER", "real-v1"),
            router_api_key=os.environ.get("CODEX_ROUTER_API_KEY", ""),
            auth_mode=os.environ.get("CODEX_ROUTER_AUTH_MODE", "file"),
            token_expires_at=os.environ.get("CODEX_ROUTER_TOKEN_EXPIRES_AT", ""),
            codex_command=os.environ.get("CODEX_ROUTER_CODEX_COMMAND", "codex"),
        )
