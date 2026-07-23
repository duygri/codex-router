import { invoke } from "@tauri-apps/api/core";
import type { Provider, ModelMapping, LogEntry, ProxyStatus, AppConfig } from "./types";

// Proxy
export const startProxy = () => invoke<void>("start_proxy");
export const stopProxy = () => invoke<void>("stop_proxy");
export const getProxyStatus = () => invoke<ProxyStatus>("get_proxy_status");

// Providers
export const getProviders = () => invoke<Provider[]>("get_providers");
export const addProvider = (p: Omit<Provider, "id" | "created_at">) => invoke<Provider>("add_provider", { provider: p });
export const updateProvider = (p: Provider) => invoke<void>("update_provider", { provider: p });
export const deleteProvider = (id: string) => invoke<void>("delete_provider", { id });
export const setDefaultProvider = (id: string) => invoke<void>("set_default_provider", { id });
export const testProvider = (id: string) => invoke<boolean>("test_provider", { id });
export const fetchProviderModels = (id: string) => invoke<string[]>("fetch_provider_models", { id });

// Model Mappings
export const getMappings = () => invoke<ModelMapping[]>("get_mappings");
export const addMapping = (m: Omit<ModelMapping, "id">) => invoke<ModelMapping>("add_mapping", { mapping: m });
export const updateMapping = (m: ModelMapping) => invoke<void>("update_mapping", { mapping: m });
export const deleteMapping = (id: string) => invoke<void>("delete_mapping", { id });

// Logs
export const getLogs = (limit?: number) => invoke<LogEntry[]>("get_logs", { limit: limit ?? 200 });
export const clearLogs = () => invoke<void>("clear_logs");

// Config
export const getConfig = () => invoke<AppConfig>("get_config");
export const updateConfig = (c: Partial<AppConfig>) => invoke<void>("update_config", { config: c });
