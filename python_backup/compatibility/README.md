# Codex compatibility status

The current MVP deliberately does not claim an official Codex OAuth contract.

- The Codex executable is present on the development machine, but it could not be executed from the current Windows environment because the process was denied access.
- No real credential file was read or copied during development.
- No command, exit code, output format, timeout, or side effect for Codex session refresh has been verified.
- Therefore the MVP supports session validation plus `reauth_required` and `unsupported` outcomes. The `refreshed` outcome remains disabled until a sanitized, user-authorized fixture and a versioned subprocess contract are verified.

Future compatibility work must use synthetic or irreversibly redacted fixtures. Never commit an account credential, raw token, personal machine path, or log containing an authorization header.
