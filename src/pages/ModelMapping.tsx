import { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, GitBranch, ChevronRight } from "lucide-react";
import { getMappings, getProviders, addMapping, deleteMapping, updateMapping } from "../api";
import type { ModelMapping, Provider } from "../types";
import { CODEX_MODELS } from "../types";

interface MappingFormProps {
  providers: Provider[];
  onSave: (m: Omit<ModelMapping, "id">) => void;
  onCancel: () => void;
}

function MappingForm({ providers, onSave, onCancel }: MappingFormProps) {
  const [form, setForm] = useState<Omit<ModelMapping, "id">>({
    codex_model: "gpt-4o",
    provider_id: providers[0]?.id ?? "",
    provider_model: "",
    enabled: true,
  });

  const selectedProvider = providers.find(p => p.id === form.provider_id);

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onCancel()}>
      <div className="modal">
        <div className="modal-title">Add Model Mapping</div>
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 20 }}>
          Map a Codex model name to a real provider model
        </p>

        <div className="form-group">
          <label className="form-label">Codex Model (what Codex sends)</label>
          <select className="form-select" value={form.codex_model} onChange={e => setForm(f => ({ ...f, codex_model: e.target.value }))}>
            {CODEX_MODELS.map(m => <option key={m} value={m}>{m}</option>)}
            <option value="*">* (wildcard — catch all)</option>
          </select>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", margin: "4px 0" }}>
          <ChevronRight size={20} style={{ color: "var(--accent)" }} />
        </div>

        <div className="form-group">
          <label className="form-label">Provider</label>
          <select className="form-select" value={form.provider_id} onChange={e => setForm(f => ({ ...f, provider_id: e.target.value, provider_model: "" }))}>
            {providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">Provider Model</label>
          {selectedProvider?.models.length ? (
            <select className="form-select" value={form.provider_model} onChange={e => setForm(f => ({ ...f, provider_model: e.target.value }))}>
              <option value="">Select model...</option>
              {selectedProvider.models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input
              className="form-input"
              value={form.provider_model}
              onChange={e => setForm(f => ({ ...f, provider_model: e.target.value }))}
              placeholder="claude-opus-4-5, gemini-2.5-pro, ..."
            />
          )}
          <span className="form-hint">The actual model ID sent to the provider</span>
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
          <button className="btn btn-primary" onClick={() => onSave(form)} disabled={!form.provider_id || !form.provider_model}>
            Save Mapping
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ModelMapping() {
  const [mappings, setMappings] = useState<ModelMapping[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    const [m, p] = await Promise.all([getMappings(), getProviders()]);
    setMappings(m);
    setProviders(p);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSave = async (data: Omit<ModelMapping, "id">) => {
    await addMapping(data);
    setShowForm(false);
    load();
  };

  const handleToggle = async (m: ModelMapping) => {
    await updateMapping({ ...m, enabled: !m.enabled });
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this mapping?")) return;
    await deleteMapping(id);
    load();
  };

  const getProviderName = (id: string) => providers.find(p => p.id === id)?.name ?? id;

  return (
    <div className="page fade-in">
      <div className="section-header">
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Model Routing</h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>
            Route Codex model names to real provider models
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          <Plus size={14} /> Add Mapping
        </button>
      </div>

      <div className="alert alert-info">
        <GitBranch size={14} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>
          When Codex sends a request with <code style={{ background: "rgba(255,255,255,0.1)", padding: "1px 4px", borderRadius: 3 }}>model: "gpt-4o"</code>,
          the proxy finds the matching mapping and forwards to the real provider model.
          Use <code style={{ background: "rgba(255,255,255,0.1)", padding: "1px 4px", borderRadius: 3 }}>*</code> as a wildcard fallback.
        </span>
      </div>

      {mappings.length === 0 ? (
        <div className="card">
          <div className="empty-state">
            <GitBranch size={36} style={{ margin: "0 auto 12px", opacity: 0.3 }} />
            <p style={{ fontWeight: 500, marginBottom: 4 }}>No mappings yet</p>
            <p>Add a mapping to route Codex models to your providers</p>
          </div>
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Codex Model</th>
                <th></th>
                <th>Provider</th>
                <th>Real Model</th>
                <th>Status</th>
                <th style={{ width: 80 }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map(m => (
                <tr key={m.id}>
                  <td><span className="tag">{m.codex_model}</span></td>
                  <td><ChevronRight size={14} style={{ color: "var(--accent)" }} /></td>
                  <td style={{ color: "var(--text-secondary)", fontSize: 12 }}>{getProviderName(m.provider_id)}</td>
                  <td><span className="tag">{m.provider_model}</span></td>
                  <td>
                    <label className="toggle">
                      <input type="checkbox" checked={m.enabled} onChange={() => handleToggle(m)} />
                      <span className="toggle-slider" />
                    </label>
                  </td>
                  <td>
                    <button className="btn btn-danger btn-icon" onClick={() => handleDelete(m.id)}>
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <MappingForm
          providers={providers}
          onSave={handleSave}
          onCancel={() => setShowForm(false)}
        />
      )}
    </div>
  );
}
