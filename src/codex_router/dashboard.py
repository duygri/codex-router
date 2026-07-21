"""Safe local status representation and HTML rendering."""

import html


def _empty_usage():
    return {
        "total_requests": 0,
        "completed_requests": 0,
        "failed_requests": 0,
        "cancelled_requests": 0,
        "active_requests": 0,
        "last_request_at": None,
        "by_model": [],
    }


def build_status(auth_adapter, store=None, config=None):
    health = auth_adapter.health_check()
    stored = {} if store is None else store.snapshot()
    real_profile = getattr(auth_adapter, "adapter_version", "") == "real-v1"
    return {
        "status": "ok",
        "auth": health.status.value,
        "adapter": getattr(auth_adapter, "adapter_version", "unknown"),
        "transport": "codex-app-server" if real_profile else "direct-test-upstream",
        "approval_policy": "on-request" if real_profile else "synthetic-test-only",
        "sandbox": "read-only" if real_profile else "synthetic-test-only",
        "codex_version": stored.get("codex_version", "unknown"),
        "pinned_adapter": stored.get("adapter_version", getattr(auth_adapter, "adapter_version", "unknown")),
        "rollback_adapter": stored.get("adapter_previous"),
        "refresh": "reauth_required_or_unsupported",
        "bind_host": getattr(config, "bind_host", "127.0.0.1"),
    }


def build_dashboard_data(auth_adapter, store, config, gateway):
    health = auth_adapter.health_check()
    real_profile = getattr(auth_adapter, "adapter_version", "") == "real-v1"
    status = {
        "state": "ok",
        "auth": health.status.value,
        "session": health.status.value,
        "transport": "codex-app-server" if real_profile else "direct-test-upstream",
        "approval_policy": "on-request" if real_profile else "synthetic-test-only",
        "sandbox": "read-only" if real_profile else "synthetic-test-only",
        "message": None,
    }
    models = []
    error = None
    try:
        if hasattr(gateway, "dashboard_models"):
            models = gateway.dashboard_models()
    except Exception as exception:
        code = getattr(exception, "code", "dashboard_data_unavailable")
        status["state"] = "degraded"
        status["message"] = "Model data is temporarily unavailable; retry refresh."
        error = {"code": code, "message": status["message"]}
    tracker = getattr(gateway, "usage_tracker", None)
    usage = tracker.snapshot() if tracker is not None else _empty_usage()
    capabilities = {
        "chat_completions": True,
        "responses": False,
        "streaming": True,
        "approval_policy": status["approval_policy"],
        "sandbox": status["sandbox"],
        "tools": False,
    }
    return {
        "status": status,
        "models": models,
        "usage": usage,
        "capabilities": capabilities,
        "error": error,
    }


def render_html(status):
    def safe(key, fallback="-"):
        return html.escape(str(status.get(key) or fallback), quote=True)

    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Codex Router Operations</title>
  <style>
    :root {
      --bg: #0b1120; --surface: #111827; --raised: #172033; --border: #2b3952;
      --text: #f8fafc; --muted: #a8b4c7; --accent: #22c55e; --warning: #f59e0b;
      --danger: #f87171; --focus: #7dd3fc; --radius: 12px;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; background: var(--bg); color: var(--text); font-family: Inter, "Segoe UI", system-ui, sans-serif; line-height: 1.5; }
    button { min-height: 44px; border: 1px solid var(--border); border-radius: 10px; background: var(--raised); color: var(--text); padding: 0 16px; font: inherit; cursor: pointer; transition: background 180ms ease, border-color 180ms ease; }
    button:hover { background: #22304a; border-color: var(--focus); }
    button:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
    .shell { width: min(1200px, calc(100% - 32px)); margin: 0 auto; padding: 24px 0 48px; }
    .topbar, .topbar-group, .status-line, .metric, .model-row, .capability { display: flex; align-items: center; }
    .topbar { justify-content: space-between; gap: 16px; margin-bottom: 32px; }
    .topbar-group { gap: 12px; flex-wrap: wrap; }
    .brand { color: var(--text); text-decoration: none; font-weight: 700; letter-spacing: -0.02em; }
    .eyebrow, .label { color: var(--muted); font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; }
    .panel { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); padding: 20px; }
    .hero { display: grid; gap: 20px; margin-bottom: 20px; }
    h1, h2, p { margin-top: 0; }
    h1 { margin-bottom: 8px; font-size: clamp(1.7rem, 4vw, 2.5rem); letter-spacing: -0.04em; }
    h2 { margin-bottom: 16px; font-size: 1rem; }
    .muted, .empty { color: var(--muted); }
    .status-line { gap: 10px; flex-wrap: wrap; }
    .badge { display: inline-flex; align-items: center; min-height: 28px; border: 1px solid var(--border); border-radius: 999px; padding: 0 10px; color: var(--muted); font-size: 0.82rem; }
    .badge.good { border-color: #19733b; color: #86efac; }
    .badge.warn { border-color: #9a6b12; color: #fcd34d; }
    .metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
    .metric { min-height: 100px; justify-content: space-between; gap: 12px; }
    .metric strong { font-size: 1.8rem; font-variant-numeric: tabular-nums; }
    .content-grid { display: grid; gap: 20px; }
    .model-list, .capability-list { display: grid; gap: 10px; }
    .model-row, .capability { justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--border); padding: 10px 0; }
    .model-row:last-child, .capability:last-child { border-bottom: 0; }
    .model-id { min-width: 0; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
    .model-meta { color: var(--muted); font-size: 0.86rem; text-align: right; }
    .footer { margin-top: 24px; color: var(--muted); font-size: 0.86rem; }
    [aria-live] { min-height: 1.5em; }
    @media (min-width: 768px) { .shell { padding-top: 40px; } .metric-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } .content-grid { grid-template-columns: minmax(0, 1.3fr) minmax(280px, 0.7fr); } }
    @media (min-width: 1024px) { .hero { grid-template-columns: minmax(0, 1fr) auto; align-items: end; } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; } }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="topbar-group"><a class="brand" href="/">Codex Router</a><span class="eyebrow">Operations dashboard</span></div>
      <button id="refresh" type="button" aria-label="Refresh dashboard">Refresh dashboard</button>
    </header>
    <main>
      <section class="hero panel" aria-labelledby="page-title">
        <div><p class="eyebrow">Local control plane</p><h1 id="page-title">Codex Router Operations</h1><p class="muted">Monitor the Codex App Server boundary without exposing credentials or prompt content.</p></div>
        <div class="status-line" aria-label="Current transport status"><span id="status-badge" class="badge">__AUTH__</span><span class="badge">__TRANSPORT__</span><span class="badge">sandbox: __SANDBOX__</span></div>
      </section>
      <p id="live-message" class="muted" aria-live="polite">Local-only status. Secrets are never displayed.</p>
      <section class="metric-grid" aria-label="Usage metrics">
        <article class="panel metric"><span class="label">Total requests</span><strong id="metric-total">—</strong></article>
        <article class="panel metric"><span class="label">Active</span><strong id="metric-active">—</strong></article>
        <article class="panel metric"><span class="label">Completed</span><strong id="metric-completed">—</strong></article>
        <article class="panel metric"><span class="label">Failed</span><strong id="metric-failed">—</strong></article>
      </section>
      <div class="content-grid">
        <section class="panel" aria-labelledby="models-title"><h2 id="models-title">Model catalog</h2><div id="models" class="model-list"><p class="empty">Loading model catalog…</p></div></section>
        <aside class="panel" aria-labelledby="capabilities-title"><h2 id="capabilities-title">Capabilities</h2><div id="capabilities" class="capability-list"><p class="empty">Loading capabilities…</p></div></aside>
      </div>
    </main>
    <footer class="footer">Transport: <strong>__TRANSPORT__</strong>. Approval: <strong>__APPROVAL__</strong>. This service is intended for loopback use.</footer>
  </div>
  <script>
    (function () {
      const refresh = document.getElementById('refresh');
      const message = document.getElementById('live-message');
      const models = document.getElementById('models');
      const capabilities = document.getElementById('capabilities');
      function text(value) { return value === null || value === undefined ? '—' : String(value); }
      function render(data) {
        const usage = data.usage || {};
        const state = (data.status || {}).state || 'degraded';
        document.getElementById('status-badge').textContent = state;
        document.getElementById('status-badge').className = 'badge ' + (state === 'ok' ? 'good' : 'warn');
        document.getElementById('metric-total').textContent = text(usage.total_requests || 0);
        document.getElementById('metric-active').textContent = text(usage.active_requests || 0);
        document.getElementById('metric-completed').textContent = text(usage.completed_requests || 0);
        document.getElementById('metric-failed').textContent = text(usage.failed_requests || 0);
        models.replaceChildren();
        if (!(data.models || []).length) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'No model data available.'; models.appendChild(empty); }
        (data.models || []).forEach(function (model) { const row = document.createElement('div'); row.className = 'model-row'; const id = document.createElement('span'); id.className = 'model-id'; id.textContent = text(model.id); const meta = document.createElement('span'); meta.className = 'model-meta'; meta.textContent = model.alias ? 'alias: ' + model.alias : text(model.owned_by); row.append(id, meta); models.appendChild(row); });
        capabilities.replaceChildren();
        Object.keys(data.capabilities || {}).forEach(function (key) { const row = document.createElement('div'); row.className = 'capability'; const label = document.createElement('span'); label.textContent = key.replace(/_/g, ' '); const value = document.createElement('strong'); value.textContent = text(data.capabilities[key]); row.append(label, value); capabilities.appendChild(row); });
        message.textContent = (data.status || {}).message || (data.error || {}).message || 'Dashboard refreshed.';
      }
      async function load() { refresh.disabled = true; refresh.textContent = 'Refreshing…'; message.textContent = 'Refreshing dashboard data…'; try { const response = await fetch('/dashboard/data', { cache: 'no-store' }); if (!response.ok) throw new Error('Dashboard data unavailable'); render(await response.json()); } catch (error) { message.textContent = 'Refresh failed. Check the local router and retry.'; } finally { refresh.disabled = false; refresh.textContent = 'Refresh dashboard'; } }
      refresh.addEventListener('click', load);
      load();
    }());
  </script>
</body>
</html>"""
    replacements = {
        "__AUTH__": safe("auth"),
        "__TRANSPORT__": safe("transport"),
        "__SANDBOX__": safe("sandbox"),
        "__APPROVAL__": safe("approval_policy"),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template
