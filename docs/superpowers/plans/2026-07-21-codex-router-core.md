# Codex Router Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Add the first 9router-like Codex-only control plane: model aliases, aggregate usage, and a responsive local operations dashboard.

**Architecture:** Keep Codex App Server as the only real-v1 transport. Add focused `ModelCatalog` and `UsageTracker` units around the existing `Gateway`, expose a safe `/dashboard/data` endpoint, and replace the minimal status HTML with a server-rendered dashboard that progressively enhances without external dependencies.

**Tech Stack:** Python 3.8 stdlib, `http.server`, SQLite metadata, server-rendered HTML/CSS/vanilla JavaScript, unittest.

---

### Task 1: Model catalog and aliases

**Files:**
- Create: `src/codex_router/model_catalog.py`
- Modify: `src/codex_router/app_server.py`
- Modify: `src/codex_router/gateway.py`
- Test: `tests/test_model_catalog.py`

- [ ] Write failing tests for explicit model pass-through, `codex` alias resolution, and unknown alias rejection.
- [ ] Add endpoint-facing tests for `/v1/models` alias advertisement, App Server `id`/`model` normalization, duplicate suppression, App Server ordering, model-ID precedence over aliases, and empty/stale catalog behavior.
- [ ] Run `PYTHONPATH=src python -m unittest tests.test_model_catalog -v` and confirm the new module/behavior fails.
- [ ] Implement the minimal catalog and connect it to real-v1 model validation.
- [ ] Preserve App Server model ordering, use a 60-second TTL, resolve only the `codex` alias, reject unknown IDs/aliases with safe 400/503 errors, and make a real model ID win if it ever collides with an alias.
- [ ] Test stale-cache preservation after refresh failure, recovery after a successful refresh, and no-cache degraded/503 behavior.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Aggregate usage tracker

**Files:**
- Create: `src/codex_router/usage.py`
- Modify: `src/codex_router/storage.py`
- Modify: `src/codex_router/gateway.py`
- Test: `tests/test_usage.py`

- [ ] Write failing tests for request counters, per-model counts, active request decrement, and secret/prompt rejection.
- [ ] Add lifecycle tests for cancellation, client disconnect cleanup, pre-admission failures, concurrent updates, restart persistence, exact aggregate JSON, and timestamp serialization.
- [ ] Run the focused usage tests and confirm failure.
- [ ] Implement aggregate-only tracking backed by safe metadata.
- [ ] Wire request lifecycle notifications without logging payloads.
- [ ] Serialize concurrent updates and persist cumulative aggregate counters across restart.
- [ ] Run focused usage and gateway tests.

### Task 3: Safe dashboard data route

**Files:**
- Modify: `src/codex_router/server.py`
- Modify: `src/codex_router/__main__.py`
- Modify: `src/codex_router/dashboard.py`
- Test: `tests/test_server.py`
- Test: `tests/test_dashboard.py`

- [ ] Write failing tests for `/dashboard/data`, model list mapping, capabilities, and secret-free response.
- [ ] Add tests for exact typed `ok`/`degraded` envelopes, stale catalog markers, safe error paths, and no API-key/prompt/event leakage.
- [ ] Run focused server/dashboard tests and confirm failure.
- [ ] Implement the route with degraded-state handling and no API-key requirement because it is safe local metadata only.
- [ ] Return the exact JSON contract, `application/json`, and `Cache-Control: no-store`; never interpolate dashboard values into executable JavaScript.
- [ ] Regression-test loopback-only binding, constant-time router-key enforcement, real-v1 bearer non-forwarding, fixed thread/turn policy messages, and dashboard secret-free errors.
- [ ] Run focused tests.

### Task 4: Operations dashboard UI

**Files:**
- Modify: `src/codex_router/dashboard.py`
- Test: `tests/test_dashboard.py`
- Test: `tests/test_public_safety.py`

- [ ] Write failing assertions for metrics, model rows, accessible labels, focus states, responsive breakpoints, and reduced-motion CSS.
- [ ] Add assertions for JavaScript-disabled readability, loading/error recovery text, WCAG-oriented contrast tokens, 375px no-horizontal-scroll CSS, safe model-ID wrapping, and no icon-only/emoji controls.
- [ ] Run the focused tests and confirm failure.
- [ ] Implement the ui-ux-pro-max dark operations design with semantic tokens and progressive enhancement.
- [ ] Use offline-safe system font fallback, focus-visible states, `aria-live` refresh feedback, 44px controls, semantic status labels, responsive breakpoints, and reduced-motion handling.
- [ ] Run tests and inspect the rendered HTML for unsafe content.

### Task 5: Full verification and publish

**Files:**
- Modify: `README.md`
- Modify: `SECURITY.md`
- Modify: `compatibility/README.md`

- [ ] Document dashboard data, model aliases, usage privacy, and Phase A limitations.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run `python -m compileall -q src tests` and `git diff --check`.
- [ ] Run a live `model/list` smoke test with the local Codex CLI.
- [ ] Commit, push, and update the draft PR after verification.
