import { useState, useEffect, useRef } from "react";
import { Trash2, RefreshCw, ScrollText, Circle } from "lucide-react";
import { getLogs, clearLogs } from "../api";
import type { LogEntry } from "../types";

function formatTime(ts: number) {
  return new Date(ts).toLocaleTimeString("en", { hour12: false });
}

function statusColor(s: number) {
  if (s < 300) return "var(--green)";
  if (s < 500) return "var(--yellow)";
  return "var(--red)";
}

export default function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [filter, setFilter] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getLogs(500).then(setLogs).catch(() => {});
  }, []);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => getLogs(500).then(setLogs).catch(() => {}), 2000);
    return () => clearInterval(t);
  }, [autoRefresh]);

  useEffect(() => {
    if (autoRefresh) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, autoRefresh]);

  const handleClear = async () => {
    if (!confirm("Clear all logs?")) return;
    await clearLogs();
    setLogs([]);
  };

  const filtered = filter
    ? logs.filter(l => l.path.includes(filter) || l.model?.includes(filter) || String(l.status).includes(filter))
    : logs;

  return (
    <div className="page fade-in" style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div className="section-header" style={{ flexShrink: 0 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Request Logs</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>
            {logs.length} entries
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="form-input"
            style={{ width: 200 }}
            placeholder="Filter logs..."
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
          <button
            className={`btn ${autoRefresh ? "btn-primary" : "btn-secondary"}`}
            onClick={() => setAutoRefresh(a => !a)}
            title="Auto-refresh"
          >
            <Circle size={8} style={{ fill: autoRefresh ? "currentColor" : "none" }} />
            Live
          </button>
          <button className="btn btn-secondary btn-icon" onClick={() => getLogs(500).then(setLogs)} title="Refresh">
            <RefreshCw size={14} />
          </button>
          <button className="btn btn-danger btn-icon" onClick={handleClear} title="Clear logs">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div className="card" style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column", padding: 0 }}>
        {/* Header row */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "80px 55px 60px 140px 1fr 70px",
          gap: 8, padding: "10px 16px",
          borderBottom: "1px solid var(--border)",
          fontSize: 11, fontWeight: 600, textTransform: "uppercase",
          letterSpacing: "0.05em", color: "var(--text-muted)", flexShrink: 0,
        }}>
          <span>Time</span>
          <span>Method</span>
          <span>Status</span>
          <span>Model</span>
          <span>Path</span>
          <span style={{ textAlign: "right" }}>Duration</span>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "0 4px" }}>
          {filtered.length === 0 ? (
            <div className="empty-state" style={{ padding: "48px 0" }}>
              <ScrollText size={36} style={{ margin: "0 auto 12px", opacity: 0.3 }} />
              <p>{filter ? "No matching logs" : "No requests yet"}</p>
            </div>
          ) : (
            filtered.map(log => (
              <div key={log.id} style={{
                display: "grid",
                gridTemplateColumns: "80px 55px 60px 140px 1fr 70px",
                gap: 8, padding: "7px 12px",
                borderBottom: "1px solid rgba(255,255,255,0.03)",
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11.5,
                alignItems: "center",
              }}>
                <span style={{ color: "var(--text-muted)" }}>{formatTime(log.timestamp)}</span>
                <span style={{ color: log.method === "GET" ? "var(--blue)" : "var(--green)", fontWeight: 500 }}>
                  {log.method}
                </span>
                <span style={{ color: statusColor(log.status), fontWeight: 600 }}>{log.status}</span>
                <span style={{ color: "var(--accent)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {log.model ?? "—"}
                </span>
                <span style={{ color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {log.path}
                  {log.error && <span style={{ color: "var(--red)", marginLeft: 8 }}>{log.error}</span>}
                </span>
                <span style={{ color: "var(--text-muted)", textAlign: "right" }}>{log.duration_ms}ms</span>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
