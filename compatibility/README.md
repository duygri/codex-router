# Codex compatibility status

The router uses the official Codex App Server for `real-v1`, but compatibility
is still versioned and fail-closed. The registry is only marked `verified` after
a known Codex CLI/App Server version produces a successful, no-cost
`model/list` check and a reviewer persists the secret-free evidence record.

- The real-v1 adapter uses the Codex CLI process as the authentication owner;
  the router does not forward a bearer token to a public HTTP API.
- The router never writes the credential store or calls an undocumented OAuth
  exchange/refresh endpoint.
- Expired CLI sessions require `codex login` again.
- The App Server bridge is text-only in the MVP and fixes approval to
  `on-request` with a `read-only` sandbox.
- Unknown Codex versions remain unverified even if a local smoke check passes.

Future compatibility work must use synthetic or irreversibly redacted fixtures. Never commit an account credential, raw token, personal machine path, or log containing an authorization header.
