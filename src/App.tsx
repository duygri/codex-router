import { useState, useEffect, useCallback } from "react";
import { HashRouter, Routes, Route, NavLink } from "react-router-dom";
import {
  LayoutDashboard, Server, GitBranch,
  ScrollText, Settings, Zap
} from "lucide-react";
import { getProxyStatus, startProxy, stopProxy } from "./api";
import type { ProxyStatus } from "./types";
import Dashboard from "./pages/Dashboard";
import Providers from "./pages/Providers";
import ModelMapping from "./pages/ModelMapping";
import Logs from "./pages/Logs";
import SettingsPage from "./pages/Settings";

export default function App() {
  const [status, setStatus] = useState<ProxyStatus>({
    running: false, port: 18080, requests_total: 0,
    requests_today: 0, tokens_total: 0, uptime_seconds: 0,
  });

  const fetchStatus = useCallback(async () => {
    try {
      const s = await getProxyStatus();
      setStatus(s);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const toggleProxy = async () => {
    try {
      if (status.running) await stopProxy();
      else await startProxy();
      await fetchStatus();
    } catch (e) { console.error(e); }
  };

  return (
    <HashRouter>
      <div className="app">
        {/* Sidebar */}
        <aside className="sidebar">
          <div className="sidebar-logo">
            <div className="logo-icon">C</div>
            <div>
              <div className="logo-text">Codex Manager</div>
              <div className="logo-version">v0.1.0</div>
            </div>
          </div>

          <nav className="sidebar-nav">
            <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <LayoutDashboard /> Dashboard
            </NavLink>
            <NavLink to="/providers" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Server /> Providers
            </NavLink>
            <NavLink to="/mappings" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <GitBranch /> Model Routing
            </NavLink>
            <NavLink to="/logs" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <ScrollText /> Logs
            </NavLink>
            <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Settings /> Settings
            </NavLink>
          </nav>

          <div className="sidebar-footer">
            <div className="proxy-status-badge">
              <div className={`status-dot ${status.running ? "running" : "stopped"}`} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 500, color: status.running ? "var(--green)" : "var(--text-muted)" }}>
                  {status.running ? "Running" : "Stopped"}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  :{status.port}
                </div>
              </div>
              <button
                className={`btn btn-icon ${status.running ? "btn-danger" : "btn-success"}`}
                onClick={toggleProxy}
                title={status.running ? "Stop proxy" : "Start proxy"}
              >
                <Zap size={12} />
              </button>
            </div>
          </div>
        </aside>

        {/* Main */}
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard status={status} onToggleProxy={toggleProxy} />} />
            <Route path="/providers" element={<Providers />} />
            <Route path="/mappings" element={<ModelMapping />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}
