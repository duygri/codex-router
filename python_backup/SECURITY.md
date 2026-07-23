# Security policy

## Supported versions

Only the latest public release and the default branch receive security fixes.

## Reporting a vulnerability

Please use a private GitHub Security Advisory for this repository. Do not open a public issue containing credentials, authorization headers, account identifiers, or an exploitable proof of concept.

When reporting, include the affected version, operating system, reproduction steps without secrets, and the minimum impact description. Redact all local paths and logs before attaching them.

## Credential safety

Never send a real Codex credential file to maintainers or commit it to this repository. The project intentionally fails closed when the local auth format is unknown and does not implement undocumented OAuth exchanges.
