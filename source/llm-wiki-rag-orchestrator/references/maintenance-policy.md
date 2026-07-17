# Maintenance Policy

- Review interval: 45 days.
- Supported local runtime: Python 3.11–3.14 with SQLite stdlib.
- Re-run release checks when Python, SQLite, PDF tooling, embedding provider, skill format, or security policy changes.
- Mark the external semantic profile `needs_review` when endpoint/model/dimensions change.
- Retain release evidence, package hash, install dry-run, and restore-drill results.
