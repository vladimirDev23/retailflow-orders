# Security Policy

## Supported version

The `main` branch is the only supported version while the project is pre-1.0.

## Reporting a vulnerability

Do not open a public issue containing credentials, exploit details, or sensitive data.
Use GitHub private vulnerability reporting when available. Otherwise contact the
repository owner through the GitHub profile with a non-sensitive summary and request a
private channel.

Include the affected commit or version, impact, prerequisites, minimal reproduction, and
suggested mitigation if known.

## Security boundaries

- Compose is a local development and demonstration topology.
- Secrets must be supplied through environment variables; repository placeholders are
  not credentials.
- `.env`, private keys, credentials, IDE files, caches, logs, and build output are
  excluded from version control and Docker build context.
- Local HS256 authentication and the deterministic payment adapter are not production
  identity or payment systems.
- CI scans complete Git history with Gitleaks and locked runtime dependencies with
  pip-audit.

If a secret is accidentally committed, deleting the file is insufficient. Revoke or
rotate it first, then clean history only through an explicitly reviewed procedure.
