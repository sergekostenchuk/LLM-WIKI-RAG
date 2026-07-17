# Changelog

## 1.0.2 — 2026-07-17

- Fixed stale-lock recovery on Windows, where a missing PID is reported as `WinError 87` rather than `ProcessLookupError`.
- Added an explicit Windows PID regression test and actionable CI failure diagnostics.

## 1.0.1 — 2026-07-17

- Fixed `status.counts.snapshots` after rollback by inventorying snapshot manifests on disk, matching the dedicated `snapshots` command.
- Added an end-to-end rollback regression check for snapshot-count consistency.

## 1.0.0 — 2026-07-17

- Added exclusive locks, budgets, security/PII scanning, redacted approval packets, telemetry, health checks, watcher/cron adapters, backed-up schema migrations, independent validation, SLOs, and incident/operations runbooks.
- Passed deterministic release checks and actual independent Codex behavioral evaluation for the local Python+SQLite profile.

## 0.2.0-beta

- Added staging, snapshots, rename identity, confirmed derived cleanup, rebuild, rollback, query, and retrieval regression.

## 0.1.0

- Added local incremental Wiki/RAG baseline.
