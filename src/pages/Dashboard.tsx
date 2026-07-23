import { useState, useEffect } from "react";
import {
  Activity, ArrowUpRight,
  Play, Square, Terminal
} from "lucide-react";
import { getLogs } from "../api";
import type { ProxyStatus, LogEntry } from "../types";

interface Props {
  status: ProxyStatus;
  onToggleProxy: () => void;
}

function formatUptime(sec: number) {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return `${h}h ${m}m`;
}

function formatNum(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export default function Dashboard({ status, onToggleProxy }: Props) {
  const [recentLogs, setRecentLogs] = useState<LogEntry[]>([]);

  useEffect(() => {
    getLogs(8).then(setRecentLogs).catch(() => {});
    const t = setInterval(() => getLogs(8).then(setRecentLogs).catch(() => {}), 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="page fade-in">
      {/* Header */}
      <div className="section-header" style={{ marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Dashboard</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>
            Codex → Provider gateway monitor
          </p>
        </div>
        <button
          className={`btn ${status.running ? "btn-danger" : "btn-success"}`}
          onClick={onToggleProxy}
        >
          {status.running ? <Square size={14} /> : <Play size={14} />}
          {status.running ? "Stop Proxy" : "Start Proxy"}
        </button>
      </div>

      {/* Stats */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value stat-green">
            {status.running ? "Active" : "Idle"}
          </div>
          <div className="stat-label">Proxy Status</div>
          <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
            <div className={`status-dot ${status.running ? "running" : "stopped"}`} />
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Port :{status.port}
            </span>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-value stat-blue">{formatNum(status.requests_today)}</div>
          <div className="stat-label">Requests Today</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
            {formatNum(status.requests_total)} total
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-value stat-purple">{formatNum(status.tokens_total)}</div>
          <div className="stat-label">Tokens Proxied</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
            All time
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-value stat-yellow">
            {status.running ? formatUptime(status.uptime_seconds) : "—"}
          </div>
          <div className="stat-label">Uptime</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
            {status.active_provider ?? "No provider"}
          </div>
        </div>
      </div>

      <div className="grid-2" style={{ gap: 16 }}>
        {/* Quick Connect */}
        <div className="card">
          <div className="card-title">Quick Connect — Codex CLI</div>
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 12 }}>
            Set these env vars then run <code style={{ color: "var(--accent)" }}>codex</code>:
          </p>
          <div className="code-block">
            <div style={{ color: "var(--text-muted)" }}># PowerShell</div>
            <div>{`$env:OPENAI_BASE_URL = "http://127.0.0.1:${status.port}/v1"`}</div>
            <div>{`$env:OPENAI_API_KEY  = "sk-codex-manager"`}</div>
            <div style={{ marginTop: 8 }}>codex</div>
          </div>
          <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 10 }}>
            All Codex Responses API calls will be routed through this proxy.
          </p>
        </div>

        {/* Recent activity */}
        <div className="card">
          <div className="card-title" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Activity size={12} /> Recent Requests
          </div>
          {recentLogs.length === 0 ? (
            <div className="empty-state" style={{ padding: "24px 0" }}>
              <Terminal size={28} style={{ margin: "0 auto 8px", opacity: 0.3 }} />
              <p>No requests yet</p>
            </div>
          ) : (
            <div>
              {recentLogs.map((log) => (
                <div key={log.id} style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "7px 0",
                  borderBottom: "1px solid rgba(255,255,255,0.04)",
                  fontSize: 12,
                }}>
                  <span className={`badge ${log.status < 300 ? "badge-green" : log.status < 500 ? "badge-yellow" : "badge-red"}`}>
                    {log.status}
                  </span>
                  <span style={{ color: "var(--text-secondary)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {log.path}
                  </span>
                  <span style={{ color: "var(--text-muted)", flexShrink: 0 }}>{log.duration_ms}ms</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Architecture diagram */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title">Gateway Architecture</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", padding: "8px 0" }}>
          {["Codex CLI", "→", "Responses API", "→", "Codex Manager :18080", "→", "Protocol Converter", "→", "Provider (Claude/Gemini/DeepSeek...)"].map((item, i) => (
            item === "→" ? (
              <ArrowUpRight key={i} size={14} style={{ color: "var(--accent)", transform: "rotate(45deg)" }} />
            ) : (
              <span key={i} className="tag">{item}</span>
            )
          ))}
        </div>
      </div>
    </div>
  );
}
