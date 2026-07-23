use std::sync::{Arc, Mutex, atomic::{AtomicBool, AtomicU64, Ordering}};
use std::time::Instant;
use crate::db::Db;
use crate::models::AppConfig;

pub struct AppState {
    pub db: Arc<Db>,
    pub proxy_running: AtomicBool,
    pub proxy_start_time: Mutex<Option<Instant>>,
    pub requests_total: AtomicU64,
    pub port: AtomicU64,
}

impl AppState {
    pub fn new(db: Arc<Db>, port: u16) -> Arc<Self> {
        Arc::new(Self {
            db,
            proxy_running: AtomicBool::new(false),
            proxy_start_time: Mutex::new(None),
            requests_total: AtomicU64::new(0),
            port: AtomicU64::new(port as u64),
        })
    }

    pub fn mark_running(&self) {
        self.proxy_running.store(true, Ordering::SeqCst);
        *self.proxy_start_time.lock().unwrap() = Some(Instant::now());
    }

    pub fn mark_stopped(&self) {
        self.proxy_running.store(false, Ordering::SeqCst);
        *self.proxy_start_time.lock().unwrap() = None;
    }

    pub fn uptime_seconds(&self) -> u64 {
        self.proxy_start_time.lock().unwrap()
            .map(|t| t.elapsed().as_secs())
            .unwrap_or(0)
    }
}
