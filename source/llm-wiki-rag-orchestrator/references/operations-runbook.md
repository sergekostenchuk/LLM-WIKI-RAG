# Operations Runbook

## Daily operation

1. Run `status` and inspect added/modified/renamed/deleted counts.
2. Run `update` without apply.
3. Review security findings, budgets, planned writes, deletion scope, and approval packets.
4. Run `update --apply` for non-destructive changes. Add `--confirm-deletions` only after verifying the raw source was intentionally removed and a snapshot will be created.
5. Run `independent_validator.py` and retain its report.
6. Run `healthcheck.py`; alert on nonzero exit.

## Scheduling

`watcher.py` and `cron_adapter.py` are adapters. Watcher is dry-run by default. Cron adapter prints a plan and never installs it. Production operators own process supervision, log rotation, credential injection, and alert routing.

## Backups

- Every mutation creates an internal snapshot of managed Wiki files and SQLite.
- Schema migration creates an additional database backup.
- Copy `.llm-wiki-rag/snapshots/` and `raw/sources/` into an independently managed backup system.
- Quarterly restore drills are required; internal snapshots alone are not disaster recovery.

## Maintenance

- Review dependency/tool state every 45 days.
- Review snapshot capacity weekly.
- Run all regression suites before upgrade.
- Never hand-edit `state.db` outside a documented migration or recovery procedure.
