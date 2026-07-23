/// converter.rs — Codex Responses API ↔ Chat Completions / Anthropic / Gemini
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

// ── Codex Responses API request ──────────────────────────────────────────────

#[derive(Debug, Deserialize)]
pub struct ResponsesRequest {
    pub model: String,
    pub input: Vec<InputItem>,
    pub instructions: Option<String>,
    pub tools: Option<Vec<Value>>,
    pub stream: Option<bool>,
    pub temperature: Option<f64>,
    pub max_output_tokens: Option<u32>,
    pub previous_response_id: Option<String>,
    pub reasoning: Option<Value>,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum InputItem {
    Message(InputMessage),
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Deserialize)]
pub struct InputMessage {
    pub role: String,
    pub content: Vec<ContentPart>,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ContentPart {
    InputText { text: String },
    InputImage { image_url: Option<Value>, detail: Option<String> },
    OutputText { text: String },
    #[serde(other)]
    Unknown,
}

// ── Chat Completions request (OpenAI-compatible) ──────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ChatMessage {
    pub role: String,
    pub content: Value,  // string or array
}

#[derive(Debug, Serialize)]
pub struct ChatRequest {
    pub model: String,
    pub messages: Vec<ChatMessage>,
    pub stream: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tools: Option<Vec<Value>>,
}

// ── Convert Responses → Chat Completions ─────────────────────────────────────

pub fn responses_to_chat(req: &ResponsesRequest) -> ChatRequest {
    let mut messages: Vec<ChatMessage> = Vec::new();

    // System / instructions
    if let Some(instructions) = &req.instructions {
        if !instructions.trim().is_empty() {
            messages.push(ChatMessage {
                role: "system".into(),
                content: json!(instructions),
            });
        }
    }

    // Input items → messages
    for item in &req.input {
        if let InputItem::Message(msg) = item {
            let content = parts_to_content(&msg.content);
            messages.push(ChatMessage {
                role: msg.role.clone(),
                content,
            });
        }
    }

    ChatRequest {
        model: req.model.clone(),
        messages,
        stream: req.stream.unwrap_or(true),
        temperature: req.temperature,
        max_tokens: req.max_output_tokens,
        tools: req.tools.clone(),
    }
}

fn parts_to_content(parts: &[ContentPart]) -> Value {
    if parts.len() == 1 {
        if let ContentPart::InputText { text } = &parts[0] {
            return json!(text);
        }
    }
    let arr: Vec<Value> = parts.iter().filter_map(|p| match p {
        ContentPart::InputText { text } => Some(json!({"type": "text", "text": text})),
        ContentPart::OutputText { text } => Some(json!({"type": "text", "text": text})),
        _ => None,
    }).collect();
    if arr.is_empty() { json!("") } else { json!(arr) }
}

// ── Convert Chat Completions SSE → Responses SSE ─────────────────────────────

/// Wraps a chat completions delta chunk into a Responses-format SSE event
pub fn chat_delta_to_responses_event(
    delta_content: &str,
    response_id: &str,
    item_id: &str,
    index: u64,
    is_first: bool,
) -> Vec<String> {
    let mut events = Vec::new();

    if is_first {
        events.push(format!(
            "data: {}\n\n",
            serde_json::to_string(&json!({
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "id": item_id,
                    "type": "message",
                    "status": "in_progress",
                    "role": "assistant",
                    "content": []
                }
            })).unwrap()
        ));
        events.push(format!(
            "data: {}\n\n",
            serde_json::to_string(&json!({
                "type": "response.content_part.added",
                "item_id": item_id,
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": ""}
            })).unwrap()
        ));
    }

    events.push(format!(
        "data: {}\n\n",
        serde_json::to_string(&json!({
            "type": "response.output_text.delta",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "delta": delta_content
        })).unwrap()
    ));

    events
}

pub fn make_responses_created_event(response_id: &str, model: &str) -> String {
    format!(
        "data: {}\n\n",
        serde_json::to_string(&json!({
            "type": "response.created",
            "response": {
                "id": response_id,
                "object": "realtime.response",
                "status": "in_progress",
                "model": model,
                "output": []
            }
        })).unwrap()
    )
}

pub fn make_responses_completed_event(
    response_id: &str, model: &str, full_text: &str,
    item_id: &str, tokens_in: u64, tokens_out: u64,
) -> Vec<String> {
    vec![
        format!("data: {}\n\n", serde_json::to_string(&json!({
            "type": "response.output_text.done",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "text": full_text
        })).unwrap()),
        format!("data: {}\n\n", serde_json::to_string(&json!({
            "type": "response.content_part.done",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": full_text}
        })).unwrap()),
        format!("data: {}\n\n", serde_json::to_string(&json!({
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "id": item_id,
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": full_text}]
            }
        })).unwrap()),
        format!("data: {}\n\n", serde_json::to_string(&json!({
            "type": "response.completed",
            "response": {
                "id": response_id,
                "object": "realtime.response",
                "status": "completed",
                "model": model,
                "output": [{
                    "id": item_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": full_text}]
                }],
                "usage": {
                    "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "total_tokens": tokens_in + tokens_out
                }
            }
        })).unwrap()),
        "data: [DONE]\n\n".into(),
    ]
}

// ── Anthropic Messages conversion ─────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct AnthropicRequest {
    pub model: String,
    pub messages: Vec<ChatMessage>,
    pub max_tokens: u32,
    pub stream: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub system: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f64>,
}

pub fn responses_to_anthropic(req: &ResponsesRequest) -> AnthropicRequest {
    let chat = responses_to_chat(req);

    let system = chat.messages.iter()
        .find(|m| m.role == "system")
        .and_then(|m| m.content.as_str().map(|s| s.to_string()));

    let messages = chat.messages.into_iter()
        .filter(|m| m.role != "system")
        .collect();

    AnthropicRequest {
        model: req.model.clone(),
        messages,
        max_tokens: req.max_output_tokens.unwrap_or(8192),
        stream: req.stream.unwrap_or(true),
        system,
        temperature: req.temperature,
    }
}
