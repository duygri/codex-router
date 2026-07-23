pub mod models;
pub mod db;
pub mod state;
pub mod proxy;
pub mod commands;

use std::sync::Arc;
use tauri::{Manager, Runtime};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use db::Db;
use state::AppState;
use commands::*;

pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env()
            .add_directive("codex_manager=debug".parse().unwrap())
            .add_directive("axum=info".parse().unwrap()))
        .init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec![]),
        ))
        .setup(|app| {
            // Initialize DB
            let data_dir = app.path().app_data_dir()
                .expect("Could not get app data dir");
            let db = Arc::new(Db::new(&data_dir).expect("Failed to init database"));

            // Load config for port
            let config = db.get_config().unwrap_or_default();
            let state = AppState::new(db, config.proxy_port);

            app.manage(Arc::clone(&state));

            // Auto-start proxy if configured
            if config.auto_start {
                let state_clone = Arc::clone(&state);
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = proxy::run_proxy(state_clone.clone(), config.proxy_port).await {
                        tracing::error!("Auto-start proxy failed: {}", e);
                    }
                });
            }

            // System tray
            let tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("Codex Manager")
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                window.hide().unwrap();
                api.prevent_close();
            }
        })
        .invoke_handler(tauri::generate_handler![
            start_proxy,
            stop_proxy,
            get_proxy_status,
            get_providers,
            add_provider,
            update_provider,
            delete_provider,
            set_default_provider,
            test_provider,
            fetch_provider_models,
            get_mappings,
            add_mapping,
            update_mapping,
            delete_mapping,
            get_logs,
            clear_logs,
            get_config,
            update_config,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Codex Manager");
}
