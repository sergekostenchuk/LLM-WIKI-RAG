# Schema Migration Policy

- Migrations are explicit: dry-run first, `--apply` second.
- Every migration backs up SQLite before changing schema.
- Unknown source versions block.
- Migration SQL is monotonic and versioned.
- A failed migration restores its database backup.
- Run all smoke, audit, retrieval, and restore checks after migration.

Current schema version: 2.
