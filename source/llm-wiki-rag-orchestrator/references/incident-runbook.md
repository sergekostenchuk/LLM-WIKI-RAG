# Incident Runbook

## Partial publication

1. Stop watcher/scheduler.
2. Preserve logs, run report, staging status, and current database files.
3. Run `audit` and independent validator without applying updates.
4. Identify the pre-mutation snapshot from the failed run.
5. Confirm raw hashes match that snapshot.
6. Run `rollback --snapshot <id>` first as dry-run, then with `--confirm`.
7. Run independent validation and health check.

## Suspected secret ingestion

1. Stop publishing and revoke/rotate the credential outside this system.
2. Preserve only redacted fingerprints in reports.
3. Remove or redact the raw source under the data-owner process.
4. Rebuild derived state after approval.
5. Treat prior vector/Wiki backups as sensitive until their retention policy removes them.

## Lock incident

Do not delete a live lock. The runtime only recovers locks older than the configured threshold whose PID is no longer alive. Preserve renamed stale-lock files as incident evidence.

## Escalation

Escalate when rollback source hashes mismatch, a snapshot is missing/corrupt, audit remains red, external embeddings have version drift, or sensitive data may exist in backups.
