/// handlers.rs — Axum route handlers
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response, Sse},
    Json,
};
use axum::response::sse::Event;
use futures::stream::{self, StreamExt};
use serde_json::{json, Value};
use std::time::Instant;
use tokio_stream::wrappers::ReceiverStream;
use uuid::Uuid;

use crate::models::{LogEntry, ProviderType};
use super::ProxyState;
use super::converter::*;

// ── /v1/responses ────────────────────────────────────────────────────────────

pub async fn handle_responses(
    State(state): State<ProxyState>,
    headers: HeaderMap,
    Json(req): Json<ResponsesRequest>,
) -> Response {
    let start = Instant::now();
    let response_id = format!("resp_{}", Uuid::new_v4().to_string().replace('-', ""));
    let item_id = format!("msg_{}", Uuid::new_v4().to_string().replace('-', ""));

    let db = &state.app_state.db;
    let codex_model = req.model.clone();

    // Resolve provider + model via mapping
    let (provider, provider_model) = match db.resolve_model(&codex_model).unwrap_or(None) {
        Some((pid, pm)) => {
            match db.get_provider(&pid).unwrap_or(None) {
                Some(p) => (p, pm),
                None => {
                    return error_response(StatusCode::BAD_GATEWAY, "Provider not found for mapping");
                }
            }
        }
        None => {
            // Fall back to default provider, use model as-is
            match db.get_default_provider().unwrap_or(None) {
                Some(p) => {
                    let pm = codex_model.clone();
                    (p, pm)
                }
                None => {
                    return error_response(StatusCode::SERVICE_UNAVAILABLE, "No provider configured. Add a provider in Settings.");
                }
            }
        }
    };

    if !provider.enabled {
        return error_response(StatusCode::SERVICE_UNAVAILABLE, "Provider is disabled");
    }

    let is_stream = req.stream.unwrap_or(true);

    // Build the upstream request based on provider type
    match provider.provider_type {
        ProviderType::Anthropic => {
            let anthropic_req = responses_to_anthropic(&req);
            let mut actual_req = anthropic_req;
            actual_req.model = provider_model.clone();
            forward_anthropic(state, provider.base_url, provider.api_key, actual_req, response_id, item_id, codex_model, provider.id, provider_model, start).await
        }
        _ => {
            // OpenAI-compatible (OpenAI, DeepSeek, Gemini via OpenAI compat, Custom)
            let mut chat_req = responses_to_chat(&req);
            chat_req.model = provider_model.clone();
            forward_openai(state, provider.base_url, provider.api_key, chat_req, response_id, item_id, codex_model, provider.id, provider_model, start).await
        }
    }
}

async fn forward_openai(
    state: ProxyState,
    base_url: String,
    api_key: String,
    chat_req: ChatRequest,
    response_id: String,
    item_id: String,
    codex_model: String,
    provider_id: String,
    provider_model: String,
    start: Instant,
) -> Response {
    let is_stream = chat_req.stream;
    let url = format!("{}/chat/completions", base_url.trim_end_matches('/'));

    let client = reqwest::Client::new();
    let upstream = client
        .post(&url)
        .bearer_auth(&api_key)
        .json(&chat_req)
        .send()
        .await;

    match upstream {
        Err(e) => {
            log_request(&state, "POST", "/v1/responses", 502, start.elapsed().as_millis() as u64, Some(provider_id), Some(codex_model), None, None, Some(e.to_string()));
            error_response(StatusCode::BAD_GATEWAY, &format!("Upstream error: {}", e))
        }
        Ok(resp) => {
            let status = resp.status().as_u16();
            if status >= 400 {
                let body = resp.text().await.unwrap_or_default();
                log_request(&state, "POST", "/v1/responses", status, start.elapsed().as_millis() as u64, Some(provider_id), Some(codex_model), None, None, Some(body.clone()));
                return (StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_GATEWAY),
                    [("content-type", "application/json")],
                    body).into_response();
            }

            if is_stream {
                stream_openai_to_responses(state, resp, response_id, item_id, codex_model, provider_id, provider_model, start).await
            } else {
                let body: Value = resp.json().await.unwrap_or(json!({}));
                let content = body["choices"][0]["message"]["content"].as_str().unwrap_or("").to_string();
                let tokens_in = body["usage"]["prompt_tokens"].as_u64().unwrap_or(0);
                let tokens_out = body["usage"]["completion_tokens"].as_u64().unwrap_or(0);
                log_request(&state, "POST", "/v1/responses", 200, start.elapsed().as_millis() as u64, Some(provider_id), Some(codex_model), Some(tokens_in), Some(tokens_out), None);

                let events = make_responses_completed_event(&response_id, &provider_model, &content, &item_id, tokens_in, tokens_out);
                let full_body = json!({
                    "id": response_id,
                    "object": "response",
                    "status": "completed",
                    "model": provider_model,
                    "output": [{"id": item_id, "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]}],
                    "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}
                });
                Json(full_body).into_response()
            }
        }
    }
}

async fn stream_openai_to_responses(
    state: ProxyState,
    resp: reqwest::Response,
    response_id: String,
    item_id: String,
    codex_model: String,
    provider_id: String,
    provider_model: String,
    start: Instant,
) -> Response {
    use futures::stream::TryStreamExt;

    let created_event = make_responses_created_event(&response_id, &provider_model);
    let mut full_text = String::new();
    let mut is_first = true;
    let mut index: u64 = 0;
    let mut tokens_in: u64 = 0;
    let mut tokens_out: u64 = 0;

    let stream = resp.bytes_stream().map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e));

    let (tx, rx) = tokio::sync::mpsc::unbounded_channel::<Result<bytes::Bytes, std::io::Error>>();

    tokio::spawn(async move {
        let mut buf = String::new();
        let mut stream = stream;
        while let Some(chunk) = stream.next().await {
            match chunk {
                Err(e) => { let _ = tx.send(Err(e)); break; }
                Ok(bytes) => {
                    buf.push_str(&String::from_utf8_lossy(&bytes));
                    while let Some(pos) = buf.find('\n') {
                        let line = buf[..pos].trim().to_string();
                        buf = buf[pos+1..].to_string();
                        if line.starts_with("data: ") {
                            let data = &line[6..];
                            if data == "[DONE]" { break; }
                            if let Ok(v) = serde_json::from_str::<Value>(data) {
                                if let Some(delta) = v["choices"][0]["delta"]["content"].as_str() {
                                    if !delta.is_empty() {
                                        let evts = chat_delta_to_responses_event(delta, "", "", index, is_first);
                                        is_first = false;
                                        index += 1;
                                        full_text.push_str(delta);
                                        for evt in evts {
                                            let _ = tx.send(Ok(bytes::Bytes::from(evt)));
                                        }
                                    }
                                }
                                // Capture usage if present
                                if let Some(u) = v["usage"].as_object() {
                                    tokens_in = u.get("prompt_tokens").and_then(|v| v.as_u64()).unwrap_or(0);
                                    tokens_out = u.get("completion_tokens").and_then(|v| v.as_u64()).unwrap_or(0);
                                }
                            }
                        }
                    }
                }
            }
        }
        // Send completion events
        for evt in make_responses_completed_event("", "", &full_text, "", tokens_in, tokens_out) {
            let _ = tx.send(Ok(bytes::Bytes::from(evt)));
        }
        log_request(&state, "POST", "/v1/responses", 200, start.elapsed().as_millis() as u64, Some(provider_id), Some(codex_model), Some(tokens_in), Some(tokens_out), None);
    });

    let rx_stream = tokio_stream::wrappers::UnboundedReceiverStream::new(rx);
    let response_stream = stream::once(async move { Ok::<_, std::io::Error>(bytes::Bytes::from(created_event)) })
        .chain(rx_stream);

    // Return SSE response
    (
        StatusCode::OK,
        [
            ("content-type", "text/event-stream"),
            ("cache-control", "no-cache"),
            ("x-accel-buffering", "no"),
        ],
        axum::body::Body::from_stream(response_stream),
    ).into_response()
}

async fn forward_anthropic(
    state: ProxyState,
    base_url: String,
    api_key: String,
    req: AnthropicRequest,
    response_id: String,
    item_id: String,
    codex_model: String,
    provider_id: String,
    provider_model: String,
    start: Instant,
) -> Response {
    let url = format!("{}/v1/messages", base_url.trim_end_matches('/'));
    let client = reqwest::Client::new();
    let upstream = client
        .post(&url)
        .header("x-api-key", &api_key)
        .header("anthropic-version", "2023-06-01")
        .json(&req)
        .send()
        .await;

    match upstream {
        Err(e) => error_response(StatusCode::BAD_GATEWAY, &e.to_string()),
        Ok(resp) => {
            let status = resp.status().as_u16();
            if status >= 400 {
                let body = resp.text().await.unwrap_or_default();
                log_request(&state, "POST", "/v1/responses", status, start.elapsed().as_millis() as u64, Some(provider_id), Some(codex_model), None, None, Some(body.clone()));
                return (StatusCode::from_u16(status).unwrap_or(StatusCode::BAD_GATEWAY),
                    [("content-type", "application/json")], body).into_response();
            }

            // Non-streaming: parse Anthropic response
            let body: Value = resp.json().await.unwrap_or(json!({}));
            let content = body["content"][0]["text"].as_str().unwrap_or("").to_string();
            let tokens_in = body["usage"]["input_tokens"].as_u64().unwrap_or(0);
            let tokens_out = body["usage"]["output_tokens"].as_u64().unwrap_or(0);

            log_request(&state, "POST", "/v1/responses", 200, start.elapsed().as_millis() as u64, Some(provider_id), Some(codex_model), Some(tokens_in), Some(tokens_out), None);

            Json(json!({
                "id": response_id,
                "object": "response",
                "status": "completed",
                "model": provider_model,
                "output": [{"id": item_id, "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": content}]}],
                "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}
            })).into_response()
        }
    }
}

// ── /v1/chat/completions (passthrough) ───────────────────────────────────────

pub async fn handle_chat_completions(
    State(state): State<ProxyState>,
    headers: HeaderMap,
    body: axum::body::Bytes,
) -> Response {
    let start = Instant::now();
    let req: Value = serde_json::from_slice(&body).unwrap_or(json!({}));
    let codex_model = req["model"].as_str().unwrap_or("unknown").to_string();

    let (provider, provider_model) = match state.app_state.db.resolve_model(&codex_model).unwrap_or(None) {
        Some((pid, pm)) => match state.app_state.db.get_provider(&pid).unwrap_or(None) {
            Some(p) => (p, pm),
            None => return error_response(StatusCode::BAD_GATEWAY, "Provider not found"),
        },
        None => match state.app_state.db.get_default_provider().unwrap_or(None) {
            Some(p) => { let pm = codex_model.clone(); (p, pm) }
            None => return error_response(StatusCode::SERVICE_UNAVAILABLE, "No provider configured"),
        }
    };

    let url = format!("{}/chat/completions", provider.base_url.trim_end_matches('/'));
    let mut patched = req;
    patched["model"] = json!(provider_model);

    let client = reqwest::Client::new();
    let upstream = client.post(&url).bearer_auth(&provider.api_key).json(&patched).send().await;

    match upstream {
        Err(e) => error_response(StatusCode::BAD_GATEWAY, &e.to_string()),
        Ok(resp) => {
            let status = resp.status();
            let ct = resp.headers().get("content-type").and_then(|v| v.to_str().ok()).unwrap_or("").to_string();
            let body = resp.bytes().await.unwrap_or_default();
            log_request(&state, "POST", "/v1/chat/completions", status.as_u16(), start.elapsed().as_millis() as u64, Some(provider.id), Some(codex_model), None, None, None);
            (status, [(axum::http::header::CONTENT_TYPE, ct)], body).into_response()
        }
    }
}

// ── /v1/models ───────────────────────────────────────────────────────────────

pub async fn handle_models(State(state): State<ProxyState>) -> impl IntoResponse {
    let codex_models = vec![
        "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.5",
        "gpt-5.2", "gpt-5.3-codex", "gpt-5.4", "gpt-5.4-mini", "gpt-5.5",
        "o3", "o4-mini",
    ];
    let data: Vec<Value> = codex_models.iter().map(|m| json!({
        "id": m, "object": "model", "created": 1700000000, "owned_by": "codex-manager"
    })).collect();
    Json(json!({"object": "list", "data": data}))
}

pub async fn handle_health() -> impl IntoResponse {
    Json(json!({"status": "ok", "service": "codex-manager"}))
}

// ── helpers ───────────────────────────────────────────────────────────────────

fn error_response(status: StatusCode, msg: &str) -> Response {
    (status, Json(json!({"error": {"message": msg, "type": "proxy_error"}}))).into_response()
}

fn log_request(
    state: &ProxyState, method: &str, path: &str,
    status: u16, duration_ms: u64,
    provider_id: Option<String>, model: Option<String>,
    tokens_in: Option<u64>, tokens_out: Option<u64>,
    error: Option<String>,
) {
    let entry = LogEntry::new(
        method.into(), path.into(), status, duration_ms,
        provider_id, model, tokens_in, tokens_out, error,
    );
    let _ = state.app_state.db.add_log(&entry);
    state.requests_total.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
}
