use anyhow::Result;
use rusqlite::{Connection, params};
use std::path::PathBuf;
use crate::models::{Provider, ProviderType, ModelMapping, LogEntry, AppConfig};

pub struct Db {
    path: PathBuf,
}

impl Db {
    pub fn new(data_dir: &PathBuf) -> Result<Self> {
        std::fs::create_dir_all(data_dir)?;
        let path = data_dir.join("codex-manager.db");
        let db = Self { path };
        db.migrate()?;
        Ok(db)
    }

    fn conn(&self) -> Result<Connection> {
        let conn = Connection::open(&self.path)?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
        Ok(conn)
    }

    fn migrate(&self) -> Result<()> {
        let conn = self.conn()?;
        conn.execute_batch(r#"
            CREATE TABLE IF NOT EXISTS providers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider_type TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                models TEXT NOT NULL DEFAULT '[]',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS model_mappings (
                id TEXT PRIMARY KEY,
                codex_model TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                provider_model TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(provider_id) REFERENCES providers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS logs (
                id TEXT PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                provider_id TEXT,
                model TEXT,
                tokens_in INTEGER,
                tokens_out INTEGER,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        "#)?;
        Ok(())
    }

    // --- Providers ---
    pub fn get_providers(&self) -> Result<Vec<Provider>> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, name, provider_type, base_url, api_key, enabled, models, is_default, created_at FROM providers ORDER BY created_at"
        )?;
        let rows = stmt.query_map([], |row| {
            let models_json: String = row.get(6)?;
            let models: Vec<String> = serde_json::from_str(&models_json).unwrap_or_default();
            Ok(Provider {
                id: row.get(0)?,
                name: row.get(1)?,
                provider_type: parse_type(row.get::<_, String>(2)?),
                base_url: row.get(3)?,
                api_key: row.get(4)?,
                enabled: row.get::<_, i32>(5)? != 0,
                models,
                is_default: row.get::<_, i32>(7)? != 0,
                created_at: row.get(8)?,
            })
        })?;
        Ok(rows.filter_map(|r| r.ok()).collect())
    }

    pub fn add_provider(&self, p: &Provider) -> Result<()> {
        let conn = self.conn()?;
        let models_json = serde_json::to_string(&p.models)?;
        conn.execute(
            "INSERT INTO providers (id,name,provider_type,base_url,api_key,enabled,models,is_default,created_at) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9)",
            params![p.id, p.name, type_str(&p.provider_type), p.base_url, p.api_key, p.enabled as i32, models_json, p.is_default as i32, p.created_at],
        )?;
        Ok(())
    }

    pub fn update_provider(&self, p: &Provider) -> Result<()> {
        let conn = self.conn()?;
        let models_json = serde_json::to_string(&p.models)?;
        conn.execute(
            "UPDATE providers SET name=?2,provider_type=?3,base_url=?4,api_key=?5,enabled=?6,models=?7,is_default=?8 WHERE id=?1",
            params![p.id, p.name, type_str(&p.provider_type), p.base_url, p.api_key, p.enabled as i32, models_json, p.is_default as i32],
        )?;
        Ok(())
    }

    pub fn delete_provider(&self, id: &str) -> Result<()> {
        let conn = self.conn()?;
        conn.execute("DELETE FROM providers WHERE id=?1", params![id])?;
        Ok(())
    }

    pub fn set_default_provider(&self, id: &str) -> Result<()> {
        let conn = self.conn()?;
        conn.execute("UPDATE providers SET is_default=0", [])?;
        conn.execute("UPDATE providers SET is_default=1 WHERE id=?1", params![id])?;
        Ok(())
    }

    pub fn get_default_provider(&self) -> Result<Option<Provider>> {
        let providers = self.get_providers()?;
        Ok(providers.into_iter().find(|p| p.is_default && p.enabled)
            .or_else(|| self.get_providers().ok()?.into_iter().find(|p| p.enabled)))
    }

    pub fn get_provider(&self, id: &str) -> Result<Option<Provider>> {
        let providers = self.get_providers()?;
        Ok(providers.into_iter().find(|p| p.id == id))
    }

    // --- Mappings ---
    pub fn get_mappings(&self) -> Result<Vec<ModelMapping>> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare(
            "SELECT id, codex_model, provider_id, provider_model, enabled FROM model_mappings ORDER BY codex_model"
        )?;
        let rows = stmt.query_map([], |row| {
            Ok(ModelMapping {
                id: row.get(0)?,
                codex_model: row.get(1)?,
                provider_id: row.get(2)?,
                provider_model: row.get(3)?,
                enabled: row.get::<_, i32>(4)? != 0,
            })
        })?;
        Ok(rows.filter_map(|r| r.ok()).collect())
    }

    pub fn add_mapping(&self, m: &ModelMapping) -> Result<()> {
        let conn = self.conn()?;
        conn.execute(
            "INSERT INTO model_mappings (id,codex_model,provider_id,provider_model,enabled) VALUES (?1,?2,?3,?4,?5)",
            params![m.id, m.codex_model, m.provider_id, m.provider_model, m.enabled as i32],
        )?;
        Ok(())
    }

    pub fn update_mapping(&self, m: &ModelMapping) -> Result<()> {
        let conn = self.conn()?;
        conn.execute(
            "UPDATE model_mappings SET codex_model=?2,provider_id=?3,provider_model=?4,enabled=?5 WHERE id=?1",
            params![m.id, m.codex_model, m.provider_id, m.provider_model, m.enabled as i32],
        )?;
        Ok(())
    }

    pub fn delete_mapping(&self, id: &str) -> Result<()> {
        let conn = self.conn()?;
        conn.execute("DELETE FROM model_mappings WHERE id=?1", params![id])?;
        Ok(())
    }

    pub fn resolve_model(&self, codex_model: &str) -> Result<Option<(String, String)>> {
        let mappings = self.get_mappings()?;
        // Exact match first
        if let Some(m) = mappings.iter().find(|m| m.enabled && m.codex_model == codex_model) {
            return Ok(Some((m.provider_id.clone(), m.provider_model.clone())));
        }
        // Wildcard fallback
        if let Some(m) = mappings.iter().find(|m| m.enabled && m.codex_model == "*") {
            return Ok(Some((m.provider_id.clone(), m.provider_model.clone())));
        }
        Ok(None)
    }

    // --- Logs ---
    pub fn add_log(&self, entry: &LogEntry) -> Result<()> {
        let conn = self.conn()?;
        conn.execute(
            "INSERT INTO logs (id,timestamp,method,path,status,duration_ms,provider_id,model,tokens_in,tokens_out,error) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
            params![entry.id, entry.timestamp, entry.method, entry.path, entry.status, entry.duration_ms as i64, entry.provider_id, entry.model, entry.tokens_in.map(|x| x as i64), entry.tokens_out.map(|x| x as i64), entry.error],
        )?;
        Ok(())
    }

    pub fn get_logs(&self, limit: u32) -> Result<Vec<LogEntry>> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare(
            "SELECT id,timestamp,method,path,status,duration_ms,provider_id,model,tokens_in,tokens_out,error FROM logs ORDER BY timestamp DESC LIMIT ?1"
        )?;
        let rows = stmt.query_map(params![limit], |row| {
            Ok(LogEntry {
                id: row.get(0)?,
                timestamp: row.get(1)?,
                method: row.get(2)?,
                path: row.get(3)?,
                status: row.get::<_, i32>(4)? as u16,
                duration_ms: row.get::<_, i64>(5)? as u64,
                provider_id: row.get(6)?,
                model: row.get(7)?,
                tokens_in: row.get::<_, Option<i64>>(8)?.map(|x| x as u64),
                tokens_out: row.get::<_, Option<i64>>(9)?.map(|x| x as u64),
                error: row.get(10)?,
            })
        })?;
        let mut v: Vec<LogEntry> = rows.filter_map(|r| r.ok()).collect();
        v.reverse();
        Ok(v)
    }

    pub fn clear_logs(&self) -> Result<()> {
        let conn = self.conn()?;
        conn.execute("DELETE FROM logs", [])?;
        Ok(())
    }

    pub fn count_logs_today(&self) -> Result<u64> {
        let conn = self.conn()?;
        use chrono::Utc;
        let start = Utc::now().date_naive().and_hms_opt(0, 0, 0).unwrap().and_utc().timestamp_millis();
        let count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM logs WHERE timestamp >= ?1", params![start], |r| r.get(0)
        )?;
        Ok(count as u64)
    }

    pub fn sum_tokens(&self) -> Result<u64> {
        let conn = self.conn()?;
        let v: Option<i64> = conn.query_row(
            "SELECT SUM(tokens_in + tokens_out) FROM logs WHERE tokens_in IS NOT NULL", [], |r| r.get(0)
        )?;
        Ok(v.unwrap_or(0) as u64)
    }

    // --- Config ---
    pub fn get_config(&self) -> Result<AppConfig> {
        let conn = self.conn()?;
        let mut stmt = conn.prepare("SELECT key, value FROM config")?;
        let mut map = std::collections::HashMap::new();
        let rows = stmt.query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })?;
        for row in rows.filter_map(|r| r.ok()) {
            map.insert(row.0, row.1);
        }

        Ok(AppConfig {
            proxy_port: map.get("proxy_port").and_then(|v| v.parse().ok()).unwrap_or(18080),
            auto_start: map.get("auto_start").map(|v| v == "true").unwrap_or(false),
            minimize_to_tray: map.get("minimize_to_tray").map(|v| v == "true").unwrap_or(true),
            log_retention_days: map.get("log_retention_days").and_then(|v| v.parse().ok()).unwrap_or(7),
            theme: map.get("theme").cloned().unwrap_or_else(|| "dark".into()),
        })
    }

    pub fn set_config_key(&self, key: &str, value: &str) -> Result<()> {
        let conn = self.conn()?;
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?1, ?2)",
            params![key, value],
        )?;
        Ok(())
    }

    pub fn update_config(&self, config: &AppConfig) -> Result<()> {
        self.set_config_key("proxy_port", &config.proxy_port.to_string())?;
        self.set_config_key("auto_start", &config.auto_start.to_string())?;
        self.set_config_key("minimize_to_tray", &config.minimize_to_tray.to_string())?;
        self.set_config_key("log_retention_days", &config.log_retention_days.to_string())?;
        self.set_config_key("theme", &config.theme)?;
        Ok(())
    }
}

fn parse_type(s: String) -> ProviderType {
    match s.as_str() {
        "anthropic" => ProviderType::Anthropic,
        "gemini"    => ProviderType::Gemini,
        "deepseek"  => ProviderType::DeepSeek,
        "custom"    => ProviderType::Custom,
        _           => ProviderType::OpenAI,
    }
}

fn type_str(t: &ProviderType) -> &'static str {
    match t {
        ProviderType::OpenAI    => "openai",
        ProviderType::Anthropic => "anthropic",
        ProviderType::Gemini    => "gemini",
        ProviderType::DeepSeek  => "deepseek",
        ProviderType::Custom    => "custom",
    }
}
