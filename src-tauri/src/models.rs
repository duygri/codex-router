use serde::{Deserialize, Serialize};
use uuid::Uuid;
use chrono::Utc;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Provider {
    pub id: String,
    pub name: String,
    #[serde(rename = "type")]
    pub provider_type: ProviderType,
    pub base_url: String,
    pub api_key: String,
    pub enabled: bool,
    pub models: Vec<String>,
    pub is_default: bool,
    pub created_at: i64,
}

impl Provider {
    pub fn new(
        name: String, provider_type: ProviderType,
        base_url: String, api_key: String,
        enabled: bool, models: Vec<String>, is_default: bool,
    ) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            name, provider_type, base_url, api_key,
            enabled, models, is_default,
            created_at: Utc::now().timestamp_millis(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ProviderType {
    OpenAI,
    Anthropic,
    Gemini,
    DeepSeek,
    Custom,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelMapping {
    pub id: String,
    pub codex_model: String,
    pub provider_id: String,
    pub provider_model: String,
    pub enabled: bool,
}

impl ModelMapping {
    pub fn new(codex_model: String, provider_id: String, provider_model: String, enabled: bool) -> Self {
        Self { id: Uuid::new_v4().to_string(), codex_model, provider_id, provider_model, enabled }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEntry {
    pub id: String,
    pub timestamp: i64,
    pub method: String,
    pub path: String,
    pub status: u16,
    pub duration_ms: u64,
    pub provider_id: Option<String>,
    pub model: Option<String>,
    pub tokens_in: Option<u64>,
    pub tokens_out: Option<u64>,
    pub error: Option<String>,
}

impl LogEntry {
    pub fn new(
        method: String, path: String, status: u16, duration_ms: u64,
        provider_id: Option<String>, model: Option<String>,
        tokens_in: Option<u64>, tokens_out: Option<u64>,
        error: Option<String>,
    ) -> Self {
        Self {
            id: Uuid::new_v4().to_string(),
            timestamp: Utc::now().timestamp_millis(),
            method, path, status, duration_ms,
            provider_id, model, tokens_in, tokens_out, error,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProxyStatus {
    pub running: bool,
    pub port: u16,
    pub requests_total: u64,
    pub requests_today: u64,
    pub tokens_total: u64,
    pub active_provider: Option<String>,
    pub uptime_seconds: u64,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub proxy_port: u16,
    pub auto_start: bool,
    pub minimize_to_tray: bool,
    pub log_retention_days: u32,
    pub theme: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            proxy_port: 18080,
            auto_start: false,
            minimize_to_tray: true,
            log_retention_days: 7,
            theme: "dark".into(),
        }
    }
}
