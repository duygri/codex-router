// Types shared between frontend and Tauri backend

export interface Provider {
  id: string;
  name: string;
  type: "openai" | "anthropic" | "gemini" | "deepseek" | "custom";
  base_url: string;
  api_key: string;
  enabled: boolean;
  models: string[];
  is_default: boolean;
  created_at: number;
}

export interface ModelMapping {
  id: string;
  codex_model: string;  // e.g. "gpt-4o", "gpt-5.5"
  provider_id: string;
  provider_model: string;  // real model name
  enabled: boolean;
}

export interface LogEntry {
  id: string;
  timestamp: number;
  method: string;
  path: string;
  status: number;
  duration_ms: number;
  provider_id?: string;
  model?: string;
  tokens_in?: number;
  tokens_out?: number;
  error?: string;
}

export interface ProxyStatus {
  running: boolean;
  port: number;
  requests_total: number;
  requests_today: number;
  tokens_total: number;
  active_provider?: string;
  uptime_seconds: number;
  error?: string;
}

export interface AppConfig {
  proxy_port: number;
  auto_start: boolean;
  minimize_to_tray: boolean;
  log_retention_days: number;
  theme: "dark" | "light";
}

export type ProviderType = Provider["type"];

export const PROVIDER_DEFAULTS: Record<ProviderType, Partial<Provider>> = {
  openai: { base_url: "https://api.openai.com/v1", name: "OpenAI" },
  anthropic: { base_url: "https://api.anthropic.com", name: "Anthropic" },
  gemini: { base_url: "https://generativelanguage.googleapis.com", name: "Google Gemini" },
  deepseek: { base_url: "https://api.deepseek.com/v1", name: "DeepSeek" },
  custom: { base_url: "https://", name: "Custom Provider" },
};

export const CODEX_MODELS = [
  "gpt-4o",
  "gpt-4o-mini",
  "gpt-4.1",
  "gpt-4.5",
  "gpt-5.2",
  "gpt-5.3-codex",
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.5",
  "o3",
  "o4-mini",
];

export const PROVIDER_COLORS: Record<ProviderType, string> = {
  openai: "#74AA9C",
  anthropic: "#CC785C",
  gemini: "#4285F4",
  deepseek: "#6366f1",
  custom: "#94a3b8",
};
