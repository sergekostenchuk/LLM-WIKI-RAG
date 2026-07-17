# Security Policy

## Supported versions

Security updates are provided for the latest stable release.

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| Earlier | No |

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities, leaked credentials, unsafe path handling, deletion boundary bypasses, or privacy defects.

Use GitHub private vulnerability reporting for `sergekostenchuk/LLM-WIKI-RAG`. Include:

- affected version and platform;
- minimal reproduction steps;
- expected and observed behavior;
- impact and affected data;
- whether credentials or personal information were exposed.

The maintainer will acknowledge a complete report as soon as practical, validate it privately, and coordinate remediation and disclosure. No fixed response-time guarantee is currently offered.

## Security boundaries

- Raw sources are authoritative and are never deleted by the runtime.
- Managed writes are constrained to documented Wiki, state, staging, snapshot, and report locations.
- Mutation commands use an exclusive lock.
- Derived deletion requires explicit confirmation and a snapshot.
- Rollback verifies raw-source hashes.
- Secret scanning is defense in depth and cannot guarantee detection of every credential or personal-data pattern.
- External embedding endpoints receive the text sent for embedding. Review provider privacy, retention, and regional processing before enabling `http-json-v1`.

Never commit `.env`, npm tokens, API keys, source documents containing secrets, knowledge-project SQLite databases, or run reports containing sensitive business metadata.
