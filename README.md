# codex-router

Local-first, Codex-only gateway with an OpenAI-compatible HTTP surface.

## Current status

This project is experimental. Codex CLI's local authentication format and refresh behavior are not treated as a stable public third-party contract. The current adapter intentionally supports only a synthetic fixture profile and fails closed for unknown real-world formats. It does not implement a direct OAuth exchange, invent an OAuth client ID, write the Codex credential file, or bypass quotas and provider controls.

Reusing a subscription-backed Codex session may be subject to OpenAI or account terms. You are responsible for confirming that your use complies with applicable terms and account policies.

## What it provides

- Loopback HTTP server on `127.0.0.1:20128` by default.
- `/health`, `/status`, and a local status page at `/`.
- OpenAI-compatible `/v1/models` and `/v1/chat/completions` routes.
- Streaming passthrough for `text/event-stream` responses.
- SQLite metadata only: no raw access or refresh tokens.
- Versioned compatibility registry with pin/rollback metadata.
- Maintainer-side compatibility checks through GitHub Actions.

## Development setup

Python 3.8 or newer is required. Install the local package:

```powershell
python -m pip install -e .
```

If an older Windows pip cannot handle a non-ASCII working-directory path, run directly from the checkout instead:

```powershell
$env:PYTHONPATH = "$pwd\src"
python -m codex_router status
```

Configure the local upstream and credential path explicitly:

```powershell
$env:CODEX_ROUTER_AUTH_FILE = "$pwd\tests\fixtures\auth\valid-session.json"
$env:CODEX_ROUTER_UPSTREAM_URL = "http://127.0.0.1:9000/v1"
codex-router status
codex-router serve
```

The fixture above is synthetic and is intended only for local tests. A real `codex login` session will remain `unsupported` until a sanitized fixture and a verified Codex CLI contract are added for that version.

Useful commands:

```text
codex-router serve [--host HOST] [--port PORT]
codex-router status
codex-router reset
```

`reset` clears router-owned SQLite metadata and in-memory state. It never deletes or modifies the Codex CLI credential store.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODEX_ROUTER_HOST` | `127.0.0.1` | Bind address |
| `CODEX_ROUTER_PORT` | `20128` | Local port |
| `CODEX_ROUTER_AUTH_FILE` | `~/.codex/auth.json` | Credential-store path |
| `CODEX_ROUTER_UPSTREAM_URL` | unset | Required upstream base URL |
| `CODEX_ROUTER_DATABASE` | `~/.codex-router/router.sqlite3` | Metadata database |
| `CODEX_ROUTER_ADAPTER` | `synthetic-v1` | Pinned adapter identifier |

Never put secrets in source control, command history, request logs, SQLite metadata, fixtures, or bug reports.

## Compatibility updates

GitHub Actions checks the official release signal on maintainer infrastructure, validates sanitized fixtures, and runs the test matrix on a schedule. The router does not phone home or silently download executable code. Adapter updates are reviewed, pinned, and rollback-capable.

## Security

Read [SECURITY.md](SECURITY.md) before testing with any account. This repository must never contain a real credential file or an authorization header.
