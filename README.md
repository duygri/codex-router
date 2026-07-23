# Codex Manager

> Local gateway proxy for OpenAI Codex CLI/Desktop — route Codex requests to any AI provider.

## Architecture

```
Codex CLI/Desktop
  → POST /v1/responses (localhost:18080)
  → [Codex Manager Proxy]  
  → Responses API → Chat Completions / Anthropic / Gemini
  → Your provider (Claude, Gemini, DeepSeek, OpenAI-compatible...)
  → SSE stream back to Codex
```

## Stack

- **Frontend**: React + TypeScript + Vite (Tauri webview)
- **Backend**: Rust (Axum HTTP proxy, SQLite, Tauri v2)
- **Desktop**: Tauri v2 (system tray, native window, auto-start)

## Features

- ✅ Codex Responses API → Chat Completions conversion
- ✅ Multi-provider support (OpenAI-compatible, Anthropic, Gemini, DeepSeek)
- ✅ Model routing/mapping (gpt-4o → claude-opus-4-5, etc.)
- ✅ Multi-account provider management
- ✅ Real-time request/response logs
- ✅ SSE streaming
- ✅ System tray + minimize to tray
- ✅ SQLite config persistence

## Prerequisites

```powershell
# 1. Install Rust
winget install Rustlang.Rustup
rustup default stable-msvc

# 2. Install Tauri CLI
cargo install tauri-cli --version "^2"

# 3. Install Node.js (LTS)
winget install OpenJS.NodeJS.LTS
```

## Development

```powershell
# Install frontend dependencies
npm install

# Run in development mode
npm run tauri dev
```

## Build

```powershell
npm run tauri build
# Output: src-tauri/target/release/bundle/
```

## Usage with Codex

```powershell
# 1. Start Codex Manager (runs proxy on :18080)

# 2. Set environment variables
$env:OPENAI_BASE_URL = "http://127.0.0.1:18080/v1"
$env:OPENAI_API_KEY  = "sk-codex-manager"

# 3. Run Codex CLI
codex "Write a hello world in Python"
```

## Provider Configuration

1. Open Codex Manager
2. Go to **Providers** → Add Provider
3. Select type (Anthropic/Gemini/DeepSeek/OpenAI-compatible)
4. Enter Base URL and API Key
5. Go to **Model Routing** → Add Mapping
6. Map `gpt-4o` → your provider + model name

## Ports

| Port | Purpose |
|------|---------|
| 18080 | Codex Manager proxy (configurable) |
| 1420 | Vite dev server (dev only) |
