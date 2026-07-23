import { useState, useEffect } from "react";
import { Save } from "lucide-react";
import { getConfig, updateConfig } from "../api";
import type { AppConfig } from "../types";

export default function Settings() {
  const [config, setConfig] = useState<AppConfig>({
    proxy_port: 18080,
    auto_start: false,
    minimize_to_tray: true,
    log_retention_days: 7,
    theme: "dark",
  });
  const [saved, setSaved] = useState(false);

  useEffect(() => { getConfig().then(setConfig).catch(() => {}); }, []);

  const handleSave = async () => {
    await updateConfig(config);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="page fade-in">
      <div className="section-header">
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Settings</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>
            Configure Codex Manager behaviour
          </p>
        </div>
        <button className={`btn ${saved ? "btn-success" : "btn-primary"}`} onClick={handleSave}>
          <Save size={14} /> {saved ? "Saved!" : "Save Changes"}
        </button>
      </div>

      <div className="grid-2">
        {/* Proxy */}
        <div className="card">
          <div className="card-title">Proxy Settings</div>

          <div className="form-group">
            <label className="form-label">Proxy Port</label>
            <input
              className="form-input"
              type="number"
              value={config.proxy_port}
              onChange={e => setConfig(c => ({ ...c, proxy_port: Number(e.target.value) }))}
              min={1024} max={65535}
            />
            <span className="form-hint">Default: 18080 (Codex default). Restart required after change.</span>
          </div>

          <div className="form-group">
            <label className="form-label">Log Retention (days)</label>
            <input
              className="form-input"
              type="number"
              value={config.log_retention_days}
              onChange={e => setConfig(c => ({ ...c, log_retention_days: Number(e.target.value) }))}
              min={1} max={90}
            />
          </div>
        </div>

        {/* App behavior */}
        <div className="card">
          <div className="card-title">Application</div>

          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>Auto-start proxy</div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Start proxy automatically on app launch</div>
              </div>
              <label className="toggle">
                <input type="checkbox" checked={config.auto_start} onChange={e => setConfig(c => ({ ...c, auto_start: e.target.checked }))} />
                <span className="toggle-slider" />
              </label>
            </div>

            <div className="divider" style={{ margin: "0" }} />

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>Minimize to tray</div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Keep running in system tray when closed</div>
              </div>
              <label className="toggle">
                <input type="checkbox" checked={config.minimize_to_tray} onChange={e => setConfig(c => ({ ...c, minimize_to_tray: e.target.checked }))} />
                <span className="toggle-slider" />
              </label>
            </div>
          </div>
        </div>
      </div>

      {/* About */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">About</div>
        <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "8px 16px", fontSize: 13 }}>
          <span style={{ color: "var(--text-muted)" }}>Version</span>
          <span>0.1.0</span>
          <span style={{ color: "var(--text-muted)" }}>Protocol</span>
          <span>OpenAI Responses API → Chat Completions / Anthropic / Gemini</span>
          <span style={{ color: "var(--text-muted)" }}>Codex port</span>
          <span style={{ fontFamily: "monospace" }}>:{config.proxy_port}</span>
          <span style={{ color: "var(--text-muted)" }}>Stack</span>
          <span>Tauri v2 + React + Rust (Axum)</span>
        </div>
      </div>
    </div>
  );
}
