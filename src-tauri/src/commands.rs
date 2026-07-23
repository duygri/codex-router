use std::sync::Arc;
use tauri::State;
use crate::state::AppState;
use crate::models::*;

type TauriResult<T> = Result<T, String>;
fn err(e: impl std::fmt::Display) -> String { e.to_string() }

// ── Proxy ─────────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn start_proxy(state: State<'_, Arc<AppState>>) -> TauriResult<()> {
    if state.proxy_running.load(std::sync::atomic::Ordering::SeqCst) {
        return Ok(());
    }
    let port = state.port.load(std::sync::atomic::Ordering::SeqCst) as u16;
    let state_clone = Arc::clone(&state);
    state_clone.mark_running();

    tokio::spawn(async move {
        let result = crate::proxy::run_proxy(state_clone.clone(), port).await;
        state_clone.mark_stopped();
        if let Err(e) = result {
            tracing::error!("Proxy stopped with error: {}", e);
        }
    });
    Ok(())
}

#[tauri::command]
pub async fn stop_proxy(state: State<'_, Arc<AppState>>) -> TauriResult<()> {
    // In a real implementation, use a CancellationToken. For now, mark stopped.
    // The actual Axum server shutdown requires a shutdown signal.
    state.mark_stopped();
    Ok(())
}

#[tauri::command]
pub async fn get_proxy_status(state: State<'_, Arc<AppState>>) -> TauriResult<ProxyStatus> {
    let running = state.proxy_running.load(std::sync::atomic::Ordering::SeqCst);
    let port = state.port.load(std::sync::atomic::Ordering::SeqCst) as u16;
    let requests_total = state.requests_total.load(std::sync::atomic::Ordering::SeqCst);
    let requests_today = state.db.count_logs_today().unwrap_or(0);
    let tokens_total = state.db.sum_tokens().unwrap_or(0);
    let default_provider = state.db.get_default_provider().unwrap_or(None).map(|p| p.name);

    Ok(ProxyStatus {
        running,
        port,
        requests_total,
        requests_today,
        tokens_total,
        active_provider: default_provider,
        uptime_seconds: state.uptime_seconds(),
        error: None,
    })
}

// ── Providers ────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_providers(state: State<'_, Arc<AppState>>) -> TauriResult<Vec<Provider>> {
    state.db.get_providers().map_err(err)
}

#[tauri::command]
pub async fn add_provider(state: State<'_, Arc<AppState>>, provider: serde_json::Value) -> TauriResult<Provider> {
    let p = Provider::new(
        provider["name"].as_str().unwrap_or("").to_string(),
        parse_provider_type(provider["type"].as_str().unwrap_or("openai")),
        provider["base_url"].as_str().unwrap_or("").to_string(),
        provider["api_key"].as_str().unwrap_or("").to_string(),
        provider["enabled"].as_bool().unwrap_or(true),
        provider["models"].as_array().map(|a| a.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect()).unwrap_or_default(),
        provider["is_default"].as_bool().unwrap_or(false),
    );
    state.db.add_provider(&p).map_err(err)?;
    Ok(p)
}

#[tauri::command]
pub async fn update_provider(state: State<'_, Arc<AppState>>, provider: Provider) -> TauriResult<()> {
    state.db.update_provider(&provider).map_err(err)
}

#[tauri::command]
pub async fn delete_provider(state: State<'_, Arc<AppState>>, id: String) -> TauriResult<()> {
    state.db.delete_provider(&id).map_err(err)
}

#[tauri::command]
pub async fn set_default_provider(state: State<'_, Arc<AppState>>, id: String) -> TauriResult<()> {
    state.db.set_default_provider(&id).map_err(err)
}

#[tauri::command]
pub async fn test_provider(state: State<'_, Arc<AppState>>, id: String) -> TauriResult<bool> {
    let provider = state.db.get_provider(&id).map_err(err)?.ok_or("Provider not found")?;
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(err)?;

    let url = match provider.provider_type {
        ProviderType::Anthropic => format!("{}/v1/models", provider.base_url.trim_end_matches('/')),
        _ => format!("{}/models", provider.base_url.trim_end_matches('/')),
    };

    let mut req = client.get(&url).bearer_auth(&provider.api_key);
    if matches!(provider.provider_type, ProviderType::Anthropic) {
        req = req.header("x-api-key", &provider.api_key).header("anthropic-version", "2023-06-01");
    }
    let resp = req.send().await.map_err(err)?;
    Ok(resp.status().is_success())
}

#[tauri::command]
pub async fn fetch_provider_models(state: State<'_, Arc<AppState>>, id: String) -> TauriResult<Vec<String>> {
    let provider = state.db.get_provider(&id).map_err(err)?.ok_or("Provider not found")?;
    let client = reqwest::Client::builder().timeout(std::time::Duration::from_secs(15)).build().map_err(err)?;
    let url = format!("{}/models", provider.base_url.trim_end_matches('/'));
    let resp: serde_json::Value = client.get(&url).bearer_auth(&provider.api_key).send().await.map_err(err)?.json().await.map_err(err)?;
    let models: Vec<String> = resp["data"].as_array()
        .map(|a| a.iter().filter_map(|v| v["id"].as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default();
    Ok(models)
}

// ── Model Mappings ────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_mappings(state: State<'_, Arc<AppState>>) -> TauriResult<Vec<ModelMapping>> {
    state.db.get_mappings().map_err(err)
}

#[tauri::command]
pub async fn add_mapping(state: State<'_, Arc<AppState>>, mapping: serde_json::Value) -> TauriResult<ModelMapping> {
    let m = ModelMapping::new(
        mapping["codex_model"].as_str().unwrap_or("").to_string(),
        mapping["provider_id"].as_str().unwrap_or("").to_string(),
        mapping["provider_model"].as_str().unwrap_or("").to_string(),
        mapping["enabled"].as_bool().unwrap_or(true),
    );
    state.db.add_mapping(&m).map_err(err)?;
    Ok(m)
}

#[tauri::command]
pub async fn update_mapping(state: State<'_, Arc<AppState>>, mapping: ModelMapping) -> TauriResult<()> {
    state.db.update_mapping(&mapping).map_err(err)
}

#[tauri::command]
pub async fn delete_mapping(state: State<'_, Arc<AppState>>, id: String) -> TauriResult<()> {
    state.db.delete_mapping(&id).map_err(err)
}

// ── Logs ──────────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_logs(state: State<'_, Arc<AppState>>, limit: Option<u32>) -> TauriResult<Vec<LogEntry>> {
    state.db.get_logs(limit.unwrap_or(200)).map_err(err)
}

#[tauri::command]
pub async fn clear_logs(state: State<'_, Arc<AppState>>) -> TauriResult<()> {
    state.db.clear_logs().map_err(err)
}

// ── Config ────────────────────────────────────────────────────────────────────

#[tauri::command]
pub async fn get_config(state: State<'_, Arc<AppState>>) -> TauriResult<AppConfig> {
    state.db.get_config().map_err(err)
}

#[tauri::command]
pub async fn update_config(state: State<'_, Arc<AppState>>, config: AppConfig) -> TauriResult<()> {
    state.port.store(config.proxy_port as u64, std::sync::atomic::Ordering::SeqCst);
    state.db.update_config(&config).map_err(err)
}

fn parse_provider_type(s: &str) -> ProviderType {
    match s {
        "anthropic" => ProviderType::Anthropic,
        "gemini"    => ProviderType::Gemini,
        "deepseek"  => ProviderType::DeepSeek,
        "custom"    => ProviderType::Custom,
        _           => ProviderType::OpenAI,
    }
}
