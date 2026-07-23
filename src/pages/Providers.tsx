import { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, Edit2, CheckCircle, XCircle, RefreshCw, Star, Server } from "lucide-react";
import {
  getProviders, addProvider, updateProvider,
  deleteProvider, setDefaultProvider, testProvider
} from "../api";
import type { Provider, ProviderType } from "../types";
import { PROVIDER_DEFAULTS, PROVIDER_COLORS } from "../types";

const TYPE_LABELS: Record<ProviderType, string> = {
  openai: "OpenAI Compatible",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  deepseek: "DeepSeek",
  custom: "Custom",
};

const TYPE_ICONS: Record<ProviderType, string> = {
  openai: "O", anthropic: "A", gemini: "G", deepseek: "D", custom: "?"
};

interface ProviderFormProps {
  initial?: Partial<Provider>;
  onSave: (p: Omit<Provider, "id" | "created_at">) => void;
  onCancel: () => void;
}

function ProviderForm({ initial, onSave, onCancel }: ProviderFormProps) {
  const [form, setForm] = useState<Omit<Provider, "id" | "created_at">>({
    name: initial?.name ?? "",
    type: initial?.type ?? "openai",
    base_url: initial?.base_url ?? "",
    api_key: initial?.api_key ?? "",
    enabled: initial?.enabled ?? true,
    models: initial?.models ?? [],
    is_default: initial?.is_default ?? false,
  });
  const [modelInput, setModelInput] = useState(form.models.join(", "));

  const handleTypeChange = (type: ProviderType) => {
    const defaults = PROVIDER_DEFAULTS[type];
    setForm(f => ({ ...f, type, name: f.name || (defaults.name ?? ""), base_url: defaults.base_url ?? f.base_url }));
  };

  const handleSave = () => {
    const models = modelInput.split(",").map(s => s.trim()).filter(Boolean);
    onSave({ ...form, models });
  };

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onCancel()}>
      <div className="modal">
        <div className="modal-title">{initial?.id ? "Edit Provider" : "Add Provider"}</div>

        <div className="form-group">
          <label className="form-label">Provider Type</label>
          <select className="form-select" value={form.type} onChange={e => handleTypeChange(e.target.value as ProviderType)}>
            {Object.entries(TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">Display Name</label>
          <input className="form-input" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="My Provider" />
        </div>

        <div className="form-group">
          <label className="form-label">Base URL</label>
          <input className="form-input" value={form.base_url} onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))} placeholder="https://api.example.com/v1" />
          <span className="form-hint">OpenAI: /v1 | Anthropic: base only | Gemini: base only</span>
        </div>

        <div className="form-group">
          <label className="form-label">API Key</label>
          <input className="form-input" type="password" value={form.api_key} onChange={e => setForm(f => ({ ...f, api_key: e.target.value }))} placeholder="sk-..." />
        </div>

        <div className="form-group">
          <label className="form-label">Models (comma separated, or leave empty to auto-fetch)</label>
          <input className="form-input" value={modelInput} onChange={e => setModelInput(e.target.value)} placeholder="claude-opus-4-5, claude-sonnet-4-5" />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <label className="toggle">
            <input type="checkbox" checked={form.enabled} onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))} />
            <span className="toggle-slider" />
          </label>
          <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>Enabled</span>
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={!form.name || !form.base_url || !form.api_key}>
            Save Provider
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Providers() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, boolean>>({});

  const load = useCallback(async () => {
    setProviders(await getProviders());
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async (data: Omit<Provider, "id" | "created_at">) => {
    if (editingProvider) {
      await updateProvider({ ...editingProvider, ...data });
    } else {
      await addProvider(data);
    }
    setShowForm(false);
    setEditingProvider(null);
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this provider?")) return;
    await deleteProvider(id);
    load();
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const ok = await testProvider(id);
      setTestResults(r => ({ ...r, [id]: ok }));
    } catch {
      setTestResults(r => ({ ...r, [id]: false }));
    } finally {
      setTesting(null);
    }
  };

  const handleSetDefault = async (id: string) => {
    await setDefaultProvider(id);
    load();
  };

  return (
    <div className="page fade-in">
      <div className="section-header">
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Providers</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>
            Configure AI providers for Codex routing
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          <Plus size={14} /> Add Provider
        </button>
      </div>

      {providers.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <Server size={36} style={{ margin: "0 auto 12px", opacity: 0.3 }} />
            <p style={{ fontWeight: 500, marginBottom: 4 }}>No providers yet</p>
            <p>Add a provider to start routing Codex requests</p>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {providers.map(p => (
            <div key={p.id} className="card" style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <div className="provider-icon" style={{ background: `${PROVIDER_COLORS[p.type]}22`, color: PROVIDER_COLORS[p.type] }}>
                {TYPE_ICONS[p.type]}
              </div>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                  <span style={{ fontWeight: 600, fontSize: 14 }}>{p.name}</span>
                  {p.is_default && <span className="badge badge-purple">Default</span>}
                  <span className={`badge ${p.enabled ? "badge-green" : "badge-gray"}`}>
                    {p.enabled ? "Enabled" : "Disabled"}
                  </span>
                  {p.id in testResults && (
                    testResults[p.id]
                      ? <span className="badge badge-green"><CheckCircle size={10} /> OK</span>
                      : <span className="badge badge-red"><XCircle size={10} /> Failed</span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", display: "flex", gap: 16 }}>
                  <span>{TYPE_LABELS[p.type]}</span>
                  <span style={{ fontFamily: "monospace" }}>{p.base_url}</span>
                  <span>{p.models.length} models</span>
                </div>
              </div>

              <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                <button className="btn btn-secondary btn-icon" onClick={() => handleTest(p.id)} disabled={testing === p.id} title="Test connection">
                  <RefreshCw size={13} className={testing === p.id ? "spin" : ""} />
                </button>
                {!p.is_default && (
                  <button className="btn btn-secondary btn-icon" onClick={() => handleSetDefault(p.id)} title="Set as default">
                    <Star size={13} />
                  </button>
                )}
                <button className="btn btn-secondary btn-icon" onClick={() => { setEditingProvider(p); setShowForm(true); }} title="Edit">
                  <Edit2 size={13} />
                </button>
                <button className="btn btn-danger btn-icon" onClick={() => handleDelete(p.id)} title="Delete">
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <ProviderForm
          initial={editingProvider ?? undefined}
          onSave={handleSave}
          onCancel={() => { setShowForm(false); setEditingProvider(null); }}
        />
      )}
    </div>
  );
}
