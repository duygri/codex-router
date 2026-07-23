/// proxy/mod.rs — Axum HTTP proxy server for Codex Responses API
use anyhow::Result;
use axum::{
    Router,
    routing::{get, post},
    middleware,
};
use std::net::SocketAddr;
use std::sync::{Arc, atomic::{AtomicBool, AtomicU64, Ordering}};
use tokio::net::TcpListener;
use tower_http::cors::{CorsLayer, Any};
use crate::state::AppState;

pub mod converter;
pub mod handlers;

#[derive(Clone)]
pub struct ProxyState {
    pub app_state: Arc<AppState>,
    pub requests_total: Arc<AtomicU64>,
    pub start_time: std::time::Instant,
}

pub async fn run_proxy(state: Arc<AppState>, port: u16) -> Result<()> {
    let proxy_state = ProxyState {
        app_state: state.clone(),
        requests_total: Arc::new(AtomicU64::new(0)),
        start_time: std::time::Instant::now(),
    };

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app = Router::new()
        .route("/v1/responses", post(handlers::handle_responses))
        .route("/v1/chat/completions", post(handlers::handle_chat_completions))
        .route("/v1/models", get(handlers::handle_models))
        .route("/health", get(handlers::handle_health))
        .layer(cors)
        .with_state(proxy_state);

    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let listener = TcpListener::bind(addr).await?;
    tracing::info!("Codex Manager proxy listening on {}", addr);

    axum::serve(listener, app).await?;
    Ok(())
}
