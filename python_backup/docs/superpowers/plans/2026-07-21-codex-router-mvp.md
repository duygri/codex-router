# Codex Router MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first, Codex-only gateway MVP that reuses a verified local Codex CLI session, exposes an OpenAI-compatible HTTP surface, records only non-secret metadata in SQLite, and fails closed when the auth contract is unknown.

**Architecture:** A Python standard-library service separates authentication, gateway transport, metadata storage, and compatibility reporting. The auth adapter reads a configured Codex credential file using synthetic-fixture-tested schema profiles; it never performs an undocumented OAuth exchange or writes the credential file. The HTTP layer forwards only after a valid session is available, and the update workflow runs in maintainer CI with adapter pinning metadata rather than silently updating user code.

**Tech Stack:** Python 3.11+, `http.server`, `sqlite3`, `subprocess`, `unittest`, GitHub Actions. No runtime third-party dependencies.

---

### Task 0: Verify the Codex auth contract before implementation

**Files:**
- Create: `compatibility/README.md`
- Create: `tests/fixtures/auth/README.md`

- [ ] **Step 1: Inspect only safe local signals**

  Check whether the `codex` executable is installed and record its version without printing credential contents. Do not read or copy a real token.

- [ ] **Step 2: Decide the MVP refresh capability**

  If no sanitized, user-authorized fixture and verified subprocess contract exist, record that the MVP supports `valid`, `reauth_required`, and `unsupported`; `refreshed` remains disabled. Do not guess a credential schema.

- [ ] **Step 3: Document fixture provenance and contract status**

  Document that fixtures must be synthetic or irreversibly redacted and that any future refresh subprocess needs verified command, exit code, output, timeout, and side-effect behavior.

- [ ] **Step 4: Commit**

  Commit message: `docs: gate implementation on verified codex auth contract`

### Task 1: Repository baseline and package skeleton

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `setup.py`
- Create: `src/codex_router/__init__.py`
- Create: `src/codex_router/__main__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

  Add a test that imports the package and asserts the package exposes a non-empty version.

- [ ] **Step 2: Run the test to verify it fails**

  Run: `python -m unittest tests.test_smoke -v`
  Expected: FAIL because the package skeleton does not exist yet.

- [ ] **Step 3: Write the minimal package and project metadata**

  Add a package version, a `python -m codex_router` entry point, and a console script named `codex-router`.

- [ ] **Step 4: Run the test to verify it passes**

  Run: `python -m unittest tests.test_smoke -v`
  Expected: PASS.

- [ ] **Step 5: Commit**

  Commit message: `chore: initialize codex router package`

### Task 2: Auth models, redaction, and fixture-tested session adapter

**Files:**
- Create: `src/codex_router/auth.py`
- Create: `src/codex_router/redaction.py`
- Create: `tests/fixtures/auth/valid-session.json`
- Create: `tests/fixtures/auth/missing-token.json`
- Create: `tests/fixtures/auth/malformed.json`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing tests**

  Cover: `detect`, configured path discovery, valid synthetic session parsing, missing-token rejection, malformed JSON rejection, unknown schema/version handling, expiry classification, secret redaction, a credential-store fingerprint that never returns raw content, and all four refresh outcomes: `valid`, `refreshed` (disabled unless contract verification enables it), `reauth_required`, and `unsupported`.

- [ ] **Step 2: Run auth tests and verify failure**

  Run: `python -m unittest tests.test_auth -v`
  Expected: FAIL because the adapter and models do not exist.

- [ ] **Step 3: Implement the minimal adapter**

  Implement typed results and an adapter that supports only the verified fixture-defined schema profile. Read atomically, check file metadata/fingerprint before and after reads, return `reauth_required` when expired, and return `unsupported` for unknown shapes/versions. Implement all four refresh outcomes, with `refreshed` disabled unless Task 0 verifies a real subprocess contract. Add `health_check` as a safe status operation that never emits secrets. Do not persist or print raw tokens.

- [ ] **Step 4: Run auth tests and verify pass**

  Run: `python -m unittest tests.test_auth -v`
  Expected: PASS.

- [ ] **Step 5: Commit**

  Commit message: `feat: add fail-closed codex session adapter`

### Task 3: SQLite metadata and configuration

**Files:**
- Create: `src/codex_router/storage.py`
- Create: `src/codex_router/config.py`
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests**

  Cover schema creation, non-secret status persistence, adapter pin/rollback metadata, reset behavior, and rejection of obvious token-shaped keys/values.

- [ ] **Step 2: Run tests and verify failure**

  Run: `python -m unittest tests.test_storage -v`
  Expected: FAIL because storage/config modules do not exist.

- [ ] **Step 3: Implement minimal storage and config**

  Use SQLite for router settings, Codex version, adapter version, health status, and update status only. Load bind address, port, auth path, upstream URL, and pinned adapter from environment/config with loopback-safe defaults. Implement reset so SQLite metadata, router-owned config, caches, and in-memory session state are cleared while the Codex credential file is untouched.

- [ ] **Step 4: Run tests and verify pass**

  Run: `python -m unittest tests.test_storage -v`
  Expected: PASS.

- [ ] **Step 5: Commit**

  Commit message: `feat: add local metadata storage and configuration`

### Task 4: OpenAI-compatible gateway and streaming transport

**Files:**
- Create: `src/codex_router/gateway.py`
- Create: `src/codex_router/server.py`
- Create: `tests/test_gateway.py`
- Create: `tests/test_server.py`

- [ ] **Step 1: Write failing tests**

  Cover `/health`, `/v1/models`, `/v1/chat/completions`, missing/expired/unknown auth responses (`401`/`503`), malformed JSON, upstream `429` passthrough with no retry, request ID/redaction behavior, stale-session rejection after credential-store mutation, and server-sent streaming passthrough using a local fake upstream.

- [ ] **Step 2: Run gateway tests and verify failure**

  Run: `python -m unittest tests.test_gateway tests.test_server -v`
  Expected: FAIL because the gateway/server modules do not exist.

- [ ] **Step 3: Implement the minimal HTTP service**

  Bind loopback by default. Add request-size limits, JSON validation, safe error codes (`auth_required`, `auth_expired`, `unsupported_codex_version`), request IDs, redacted diagnostics, upstream forwarding, and chunked streaming passthrough. Recheck the auth-store identity before forwarding and refuse stale cached sessions. Do not log prompts, completions, or authorization headers.

- [ ] **Step 4: Run gateway tests and verify pass**

  Run: `python -m unittest tests.test_gateway tests.test_server -v`
  Expected: PASS.

- [ ] **Step 5: Commit**

  Commit message: `feat: add openai-compatible local gateway`

### Task 5: Local dashboard, CLI, and compatibility status

**Files:**
- Create: `src/codex_router/dashboard.py`
- Modify: `src/codex_router/__main__.py`
- Create: `tests/test_dashboard.py`
- Create: `compatibility/registry.json`

- [ ] **Step 1: Write failing tests**

  Cover the dashboard status payload, CLI `serve`/`status`/`reset` argument parsing, reset behavior, and adapter pin/rollback display without secret fields.

- [ ] **Step 2: Run tests and verify failure**

  Run: `python -m unittest tests.test_dashboard -v`
  Expected: FAIL because dashboard/CLI functionality does not exist.

- [ ] **Step 3: Implement the minimal dashboard and CLI**

  Serve a local HTML status page and JSON status endpoint. Show Codex detection, adapter version, health, refresh capability, pin, rollback target, and safe next steps. Add `codex-router serve`, `codex-router status`, and `codex-router reset` commands. Reset must not touch the Codex CLI credential store.

- [ ] **Step 4: Run tests and verify pass**

  Run: `python -m unittest tests.test_dashboard -v`
  Expected: PASS.

- [ ] **Step 5: Commit**

  Commit message: `feat: add local status dashboard and compatibility registry`

### Task 6: Public-repository safety and maintainer CI

**Files:**
- Create: `README.md`
- Create: `LICENSE`
- Create: `SECURITY.md`
- Create: `.github/workflows/compatibility.yml`
- Create: `tests/test_public_safety.py`
- Create: `tests/test_permissions.py`
- Create: `tests/test_compatibility.py`

- [ ] **Step 1: Write failing safety checks**

  Assert repository fixtures are synthetic, prohibited token keys are absent from committed fixtures, the README contains the experimental/ToS warning, the workflow runs on maintainer CI rather than user runtime, registry fields are complete, applying an adapter pin selects exactly that version, rollback restores the previous known-good version, failed compatibility checks do not update the pinned adapter, and platform permission handling is covered or explicitly skipped with a reason.

- [ ] **Step 2: Run safety tests and verify failure**

  Run: `python -m unittest tests.test_public_safety -v`
  Expected: FAIL because public-repository files do not exist.

- [ ] **Step 3: Implement documentation, license, security policy, and workflow**

  Document setup, `codex login`, environment variables, the fact that the exact Codex auth schema is not a public stable contract, no direct OAuth exchange, adapter pin/rollback, local-only defaults, and limitations. Add CI that validates registry fields, runs the supported-version fixture matrix, detects an intentionally changed fixture, exercises apply-pin and rollback behavior, and leaves the pinned adapter unchanged when checks fail. Add platform-aware permission checks for Windows ACLs and POSIX modes where applicable.

- [ ] **Step 4: Run all tests and safety checks**

  Run: `python -m unittest discover -s tests -v`
  Expected: PASS with zero failures.

- [ ] **Step 5: Commit**

  Commit message: `docs: prepare safe public release workflow`

### Task 7: Final verification and GitHub publication

**Files:**
- Read-only verification: `src/codex_router/`, `tests/`, `compatibility/registry.json`, `.github/workflows/compatibility.yml`, `README.md`, `LICENSE`, `SECURITY.md`, `pyproject.toml`, and `.gitignore`.

- [ ] **Step 1: Run the full verification suite**

  Run: `python -m unittest discover -s tests -v` and `python -m compileall -q src tests`.

- [ ] **Step 2: Run a local smoke check**

  Start the service with a synthetic auth fixture and fake upstream, verify `/health`, `/v1/models`, one non-streaming request, one streaming request, missing/expired auth errors, reset preserving the credential file, and shutdown cleanly.

- [ ] **Step 3: Review the diff for secrets and scope**

  Run: `git diff --check`, inspect `git status`, and search the exact files listed above for token-shaped values, personal machine paths, and accidental credential fixtures. If a verification failure is found, return to the originating task and fix only its already-listed files before rerunning Task 7.

- [ ] **Step 4: Confirm verification outcome**

  If verification fails, stop and return to the originating task; do not modify files under Task 7. Once all checks pass, the originating task's commit history is the final implementation record.

- [ ] **Step 5: Push the implementation branch and publish the public repository**

  Push `codex/implement-router` to `origin`, then update the public repository's default branch only after verification succeeds.
