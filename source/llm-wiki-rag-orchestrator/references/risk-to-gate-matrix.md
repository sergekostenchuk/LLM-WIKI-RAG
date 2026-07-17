# Risk To Gate Matrix

| Risk | Gate |
|---|---|
| Local mutation | before-state snapshot, managed write zones, post-audit |
| Deletion | raw already absent, explicit confirmation, snapshot, blast-radius report |
| Secret/privacy | redacted scan, block secrets, PII review/block, fingerprint approval |
| External embeddings | HTTPS, no redirects/userinfo/query token, env-only token, dimension check, call budget |
| Concurrency | exclusive lock and stale-owner verification |
| Migration | dry-run, database backup, known version, post-check |
