# Security policy

## Supported versions

Only the latest public release and the default branch receive security fixes.

## Reporting a vulnerability

Please use a private GitHub Security Advisory for this repository. Do not open a public issue containing credentials, authorization headers, account identifiers, or an exploitable proof of concept.

When reporting, include the affected version, operating system, reproduction steps without secrets, and the minimum impact description. Redact all local paths and logs before attaching them.

## Credential safety

Never send a real Codex credential file to maintainers or commit it to this repository. The project intentionally fails closed when the local auth format is unknown and does not implement undocumented OAuth exchanges.

The router is loopback-only. Every `/v1/*` request requires the separate
`X-Codex-Router-Key`; `/health`, `/status`, and `/` contain safe status only.

For `real-v1`, the router starts the locally installed Codex App Server over
stdio and does not forward a Codex access or refresh token to an HTTP upstream.
Each request uses a short-lived App Server process with `approvalPolicy=on-request`,
`sandbox=read-only`, and an ephemeral thread. Client attempts to override these
policies, invoke tools, or approve commands are rejected. Only agent text
deltas are exposed, and App Server event payloads are not logged. The
`/v1/responses` surface is a text-only translation layer; tools and multimodal
inputs are rejected.

The dashboard at `/` and its safe `/dashboard/data` endpoint expose only local
operational metadata. `/dashboard/data` does not require the router key because
it contains no credentials, prompt content, response content, or raw App Server
events; `/v1/*` continues to require `X-Codex-Router-Key`. Usage tracking stores
only aggregate counters, validated model identifiers, and validated numeric
token totals when App Server reports them.

`CODEX_ROUTER_CODEX_COMMAND` must point to a trusted local Codex CLI executable;
the router invokes it without a shell. Treat the router API key as a local
code-execution capability: keep it secret, keep the bind on loopback, and do
not expose the port through a proxy or tunnel without a separate authenticated
boundary. The App Server protocol is experimental, so compatibility evidence
must identify the exact CLI version before a release is marked verified.
