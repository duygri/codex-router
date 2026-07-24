# Codex Router Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secure, bounded `codex-router doctor` command and `/ready` endpoint that verify Codex CLI/App Server/model readiness without sending prompts or exposing secrets.

**Architecture:** Add a focused `readiness.py` module with typed safe check results, an injectable clock, and a serialized 10-second cache for the HTTP server. The probe will use one App Server JSON-RPC process for `initialize`, `initialized`, and `model/list`, while the CLI doctor performs an independent uncached probe before SQLite opens. Keep `/health` process-only and pass one shared readiness provider into the HTTP server and dashboard.

**Tech Stack:** Python 3.8+, stdlib `subprocess`, `threading`, `time`, `json`, `unittest`, existing Codex App Server bridge, model catalog validator, and loopback HTTP server.

---

## File map and ownership

- Create `src/codex_router/readiness.py`: safe check/report schema, strict probe orchestration, cache/coordinator, fake-clock seams.
- Modify `src/codex_router/config.py`: preserve raw invalid env values and validate effective configuration fail-closed.
- Modify `src/codex_router/model_catalog.py`: expose/reuse the existing safe model-ID validator without changing normal catalog behavior.
- Modify `src/codex_router/app_server.py`: add one-process readiness probe and strict raw model-list validation; preserve normal request/list behavior.
- Modify `src/codex_router/__main__.py`: add `doctor`, validate effective serve overrides before store/gateway, and wire one provider.
- Modify `src/codex_router/server.py`: optional readiness provider, `/ready`, and compatibility-preserving `run_server` behavior.
- Modify `src/codex_router/dashboard.py`: render shared readiness state and first fixed failure message.
- Modify `README.md` and `SECURITY.md`: document commands, endpoint, timeouts, cache and no-secret guarantees.
- `tests/test_config.py`: owns strict config validation tests.
- `tests/test_model_catalog.py`: owns shared validator tests.
- `tests/test_app_server.py`: owns process/protocol/cleanup tests.
- `tests/test_readiness.py`: owns report/coordinator/doctor-probe tests.
- `tests/test_cli_integration.py`: owns parser, doctor ordering and exit-code tests after CLI support exists.
- `tests/test_server.py`: owns `/ready`/`/health` route tests.
- `tests/test_dashboard.py`: owns dashboard readiness rendering tests.

### Task 1: Make configuration validation strict and reusable

**Files:** `src/codex_router/config.py`, `tests/test_config.py`

- [ ] **Step 1: Write failing tests** for unknown adapters, non-loopback hosts, invalid ports, negative queue size, non-finite/too-small queue timeout, valid values, and preservation of invalid raw environment values for later rejection.
- [ ] **Step 2: Run the focused tests and verify they fail** because current parsing silently clamps/defaults invalid values and can raise on malformed ports.
- [ ] **Step 3: Implement `validate_router_config(config, host=None, port=None)`** with accepted adapters `real-v1`/`synthetic-v1`, loopback host, port `1..65535`, queue size `>= 0`, finite queue timeout `>= 0.1`, and safe `ConfigError` code/message values. Use `is not None` for CLI overrides.
- [ ] **Step 4: Preserve valid existing defaults and make invalid values explicit** so callers can reject them before opening SQLite or constructing a gateway; missing router key is a configuration failure for `serve`/`doctor` with a fixed safe message.
- [ ] **Step 5: Run focused config tests and verify they pass.**
- [ ] **Step 6: Commit** with `git commit -m "feat: validate router readiness configuration"`.

### Task 2: Expose a shared safe model-ID validator

**Files:** `src/codex_router/model_catalog.py`, `tests/test_model_catalog.py`

- [ ] **Step 1: Write failing tests** for accepted/rejected model IDs and confirm normal catalog normalization still skips/handles legacy entries exactly as before.
- [ ] **Step 2: Run the focused tests and verify they fail** because readiness cannot reuse the validator through a stable helper.
- [ ] **Step 3: Extract/export the existing safe model-ID predicate** as a small helper used by normal catalog code and readiness strict validation; do not change normal catalog behavior in this task.
- [ ] **Step 4: Run model catalog tests and verify they pass.**
- [ ] **Step 5: Commit** with `git commit -m "refactor: share safe model identifier validation"`.

### Task 3: Add strict one-process App Server probe primitives

**Files:** `src/codex_router/app_server.py`, `tests/test_app_server.py`

- [ ] **Step 1: Write failing tests** for the exact sequence `initialize`, `initialized`, `model/list`, with no `thread/start` or `turn/start`; include missing/empty catalog, mixed valid/malformed entries, both `id` and `model`, unknown fields, oversized JSON lines, timeout, and cleanup.
- [ ] **Step 2: Run the focused tests and verify they fail** because the bridge has no readiness-only session operation.
- [ ] **Step 3: Implement a readiness session method** that bypasses normal request admission, starts one process, performs the exact JSON-RPC sequence, uses independent 3-second handshake/model-list deadlines, and closes in `finally`.
- [ ] **Step 4: Implement strict raw catalog validation**: each item must have a safe `id` or `model`; if both are present they must agree; only known non-secret Codex metadata fields are allowed, and unknown fields fail the whole list. Empty, invalid, conflicting, mixed, protocol and transport cases map to stable readiness codes while preserving normal `list_model_items` behavior.
- [ ] **Step 5: Enforce 1 MiB App Server JSON-line cap** and safe failure on overflow; keep version-output cap in the CLI probe task. Ensure terminate→kill escalation and process-group cleanup when supported.
- [ ] **Step 6: Run App Server tests and verify they pass.**
- [ ] **Step 7: Commit** with `git commit -m "feat: add bounded Codex readiness probe"`.

### Task 4: Add readiness reports, cache and coordination

**Files:** `src/codex_router/readiness.py`, `tests/test_readiness.py`

- [ ] **Step 1: Write failing tests** for the exact four-check envelope, real-v1 success/failure mapping, synthetic-v1 skipped checks, missing-key invalid config, unexpected `diagnostic_failed`, and all allowlisted error codes.
- [ ] **Step 2: Write failing coordination tests** for 10-second fake-clock cache reuse of both ready and not-ready results, 2-second waiter timeout, non-caching of the synthetic waiter-timeout response, release of waiters after failed probes, and doctor uncached independence.
- [ ] **Step 3: Run tests and verify they fail** because no report type/coordinator exists.
- [ ] **Step 4: Implement immutable safe check/report structures** with only fixed allowlisted codes/messages; all reports always contain `config`, `codex_cli`, `app_server`, and `model_catalog`, with optional version/model count omitted on failure/skip.
- [ ] **Step 5: Implement `ReadinessProbe.check()`** with serialized in-flight work, injected clock, 10-second TTL, 2-second waiter deadline, cached failures, and background completion that fills the cache after a waiter gives up. A waiter timeout returns a complete safe envelope with `app_server.code=readiness_wait_timeout`, dependent catalog check skipped, and is not itself cached.
- [ ] **Step 6: Implement `doctor_report()`** as an independent, uncached probe with the same strict config, 2-second CLI version timeout, 3-second App Server deadlines, 64 KiB version cap, and JSON-only output data.
- [ ] **Step 7: Run readiness tests and verify they pass without real sleeps.**
- [ ] **Step 8: Commit** with `git commit -m "feat: add safe readiness report coordinator"`.

### Task 5: Add CLI doctor and validate serve startup order

**Files:** `src/codex_router/__main__.py`, `tests/test_cli_integration.py`

- [ ] **Step 1: Write failing tests** for parser support, doctor exit codes `0/1/2`, JSON-only secret-free output, no metadata directory/database creation, and rejection before `MetadataStore`/`Gateway` construction.
- [ ] **Step 2: Run the focused tests and verify they fail** because the parser lacks `doctor` and commands currently open the store before dispatch.
- [ ] **Step 3: Add `doctor` before `_open_store`**; validate config, run the independent report, print only JSON, return `0` ready, `1` not-ready/unexpected, and `2` invalid-config. Never print CLI stderr, paths, command lines or router key.
- [ ] **Step 4: Validate effective `serve --host/--port` before store/gateway** and pass the effective values into the shared readiness provider; unknown adapters and missing keys never bind a socket.
- [ ] **Step 5: Run CLI tests and verify they pass.**
- [ ] **Step 6: Commit** with `git commit -m "feat: add Codex doctor diagnostics"`.

### Task 6: Expose `/ready` while preserving `/health` and wrappers

**Files:** `src/codex_router/server.py`, `tests/test_server.py`

- [ ] **Step 1: Write failing tests** for `/health` not invoking readiness, `/ready` 200/503 mapping, exact safe envelope, non-cached waiter timeout, synthetic-v1 skipped checks, loopback bind, and existing positional `create_server`/`run_server` compatibility.
- [ ] **Step 2: Run tests and verify they fail** because `create_server` has no readiness provider or `/ready` route.
- [ ] **Step 3: Add an optional `readiness_provider` at the end of `create_server` parameters** and route `GET /ready` to it; return `503` only for `not_ready`, `200` for `ready`, and fixed safe JSON for unexpected failures.
- [ ] **Step 4: Keep `/health` completely readiness-free** and preserve existing route/key behavior; update `run_server` to pass through an optional provider without breaking old callers.
- [ ] **Step 5: Run server tests and verify they pass.**
- [ ] **Step 6: Commit** with `git commit -m "feat: expose Codex readiness endpoint"`.

### Task 7: Wire dashboard and complete verification

**Files:** `src/codex_router/dashboard.py`, `README.md`, `SECURITY.md`, `tests/test_dashboard.py`

- [ ] **Step 1: Write failing dashboard tests** for shared readiness consumption, first fixed failed-check message/code, no extra probe invocation, safe key handling, and responsive HTML marker rendering.
- [ ] **Step 2: Implement dashboard readiness state** using the same provider as HTTP; never spawn an independent probe, render no raw detail, and preserve existing dark responsive UI/accessibility behavior.
- [ ] **Step 3: Update README/SECURITY** with `codex-router doctor`, `/ready`, exact timeouts/caching, synthetic skips, strict catalog validation, cleanup and no-prompt/no-secret guarantees.
- [ ] **Step 4: Run the full suite** with `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` and require all tests pass except documented Windows-policy skips.
- [ ] **Step 5: Run compile, diff, secret scan, and manual no-cost `model/list` smoke**; never send a prompt in diagnostics.
- [ ] **Step 6: Run browser smoke at 375px/1024px if HTML changed; confirm no horizontal overflow and safe readiness rendering.**
- [ ] **Step 7: Commit** with `git commit -m "feat: document and verify Codex readiness operations"`.
- [ ] **Step 8: Push branch, update PR #1, and confirm GitHub Actions checks pass** as optional publishing handoff after implementation verification.
