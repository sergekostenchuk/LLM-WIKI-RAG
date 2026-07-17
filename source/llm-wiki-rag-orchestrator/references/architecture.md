# Architecture

## State ownership

- Raw sources are user-owned and immutable to the skill.
- Generated source pages are tool-owned.
- User-authored semantic Wiki pages outside `wiki/sources/` are not overwritten.
- SQLite owns the active source manifest and chunk records.
- Run reports are append-only evidence.

## Pipeline

```text
scan -> ChangeSet -> extract -> Wiki page -> chunks/vectors -> audit -> accept
```

`update` without `--apply` terminates after planning. Apply renders into a run-specific staging namespace, creates a before-state snapshot, publishes managed files, commits SQLite state, and runs an independent audit. Deletion requires an additional explicit confirmation.

## MVP vector baseline

`hashing-v1` tokenizes Unicode words, maps them into a fixed dimensional vector with SHA256, and L2-normalizes the counts. It is deterministic and dependency-free. `http-json-v1` is an opt-in HTTPS adapter whose endpoint, model, dimensions, and token environment-variable name must be configured and independently verified.

## Version rules

- CLI schema version: `1`.
- Generator version: `1.0.0`.
- Vector provider: `hashing-v1`.
- A provider or dimension change requires full reindexing.
