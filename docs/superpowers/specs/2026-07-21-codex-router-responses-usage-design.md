# Codex Router Phase B: Responses and Usage Design

## Scope

Phase B makes the Codex-only gateway closer to a practical 9router-style local
endpoint. It adds a text-only `/v1/responses` compatibility surface and numeric
usage aggregates from the official Codex App Server. It does not add another
provider, direct bearer forwarding, client-controlled permissions, tools, or
multimodal input.

## Responses contract

- `POST /v1/responses` is protected by `X-Codex-Router-Key` and loopback-only
  server binding remains mandatory.
- Accepted request fields are `model`, `input`, `instructions`, and `stream`.
- `input` may be one text string or an array of text `message` items with
  `system`, `user`, or `assistant` roles. Text parts may use
  `input_text`, `output_text`, or the compatibility `text` type.
- The router translates the request to the existing text-only App Server
  `thread/start`/`turn/start` path. It never forwards client permission,
  approval, sandbox, tools, function, response-format, or multimodal options.
- Non-stream responses use the Responses shape with `output_text` and one
  assistant message. Stream responses emit typed `response.created`,
  `response.output_text.delta`, `response.output_text.done`, and
  `response.completed` events.
- Unsupported fields and non-text content return safe `400` errors. Synthetic
  test adapters return explicit `501`; they are not treated as Codex.

## Usage privacy and lifecycle

- App Server `thread/tokenUsage/updated` notifications are parsed in memory.
- Only non-negative numeric totals are accepted: input, cached input, output,
  reasoning output, and total tokens.
- Cumulative notifications are delta-counted per request handle, so repeated
  snapshots do not double-count. Malformed events are ignored and their raw
  payloads are never persisted or returned.
- SQLite stores only the aggregate counters and a boolean indicating whether a
  numeric token report was observed. Prompt text, response text, headers,
  credentials, and raw App Server events remain excluded.

## Dashboard requirements

The local server-rendered dashboard exposes the endpoint base URL, header name,
and `codex` alias without exposing the header value. It shows token metrics as
`—` until App Server reports valid numeric usage, and labels Responses as
text-only. The UI remains offline-safe, responsive at 375/768/1024/1440px,
keyboard-focusable, and respects `prefers-reduced-motion`.
