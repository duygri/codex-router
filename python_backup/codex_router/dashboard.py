"""Safe local status representation and HTML rendering."""

import html


def build_status(auth_adapter, store=None, config=None):
    health = auth_adapter.health_check()
    stored = {} if store is None else store.snapshot()
    return {
        "status": "ok",
        "auth": health.status.value,
        "adapter": getattr(auth_adapter, "adapter_version", "unknown"),
        "codex_version": stored.get("codex_version", "unknown"),
        "pinned_adapter": stored.get("adapter_version", getattr(auth_adapter, "adapter_version", "unknown")),
        "rollback_adapter": stored.get("adapter_previous"),
        "refresh": "reauth_required_or_unsupported",
        "bind_host": getattr(config, "bind_host", "127.0.0.1"),
    }


def render_html(status):
    rows = []
    for key in ("auth", "adapter", "codex_version", "pinned_adapter", "rollback_adapter", "refresh", "bind_host"):
        rows.append("<tr><th>{}</th><td>{}</td></tr>".format(html.escape(key), html.escape(str(status.get(key) or "-"))))
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Codex Router</title>"
        "<style>body{{font-family:system-ui;max-width:720px;margin:40px auto;padding:0 16px}}"
        "table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;border-bottom:1px solid #ddd;padding:8px}}</style>"
        "</head><body><h1>Codex Router</h1><p>Local status only. Secrets are never displayed.</p>"
        "<table>{}</table></body></html>"
    ).format("".join(rows))
