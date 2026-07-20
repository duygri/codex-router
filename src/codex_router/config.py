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
    adapter_version: str = "synthetic-v1"

    @classmethod
    def from_env(cls):
        home = os.path.expanduser("~")
        default_db_dir = os.path.join(home, ".codex-router")
        return cls(
            bind_host=os.environ.get("CODEX_ROUTER_HOST", "127.0.0.1"),
            port=int(os.environ.get("CODEX_ROUTER_PORT", "20128")),
            auth_path=os.environ.get("CODEX_ROUTER_AUTH_FILE", os.path.join(home, ".codex", "auth.json")),
            upstream_url=os.environ.get("CODEX_ROUTER_UPSTREAM_URL", ""),
            database_path=os.environ.get("CODEX_ROUTER_DATABASE", os.path.join(default_db_dir, "router.sqlite3")),
            adapter_version=os.environ.get("CODEX_ROUTER_ADAPTER", "synthetic-v1"),
        )
