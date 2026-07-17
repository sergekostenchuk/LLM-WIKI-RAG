# Worker Contracts

## Shared contract

Every worker returns `worker_id`, `status`, `inputs`, `outputs`, `evidence_paths`, `failure_mode`, and `handoff`. Status is one of `done`, `blocked`, or `failed`. Retry counts are finite.

| Worker | Input | Output | Write zone | Acceptance gate |
|---|---|---|---|---|
| detector | project path + DB state | ChangeSet | run report | every file has path/hash/status |
| ingestor | changed files | normalized text | memory/run staging | parser success and size limit |
| extractor | normalized text | source-page patch | run staging | provenance frontmatter present |
| reconciler | page patches | generated Wiki | managed Wiki zone | no unowned file overwritten |
| indexer | normalized text | chunks/vectors | SQLite chunks | chunks reference active source hash |
| validator | filesystem + DB | ValidationReport | reports only | zero errors |
| publisher | accepted patches + snapshot | active files/state | managed zones | explicit apply; deletion needs confirmation |

## Context-review checkpoints

1. After detection: scope, rename, and deletion review.
2. After ingestion: parser and provenance review.
3. After Wiki/RAG creation: independent audit.
4. Before destructive publish: snapshot proof and confirmation.
5. Before acceptance: command evidence and report completeness.

Worker-specific prompts live in `agents/`.
