# LLM-WIKI-RAG Publisher

Purpose: activate only accepted additions and modifications after explicit apply intent.

- Read zone: accepted ChangeSet, Wiki patches, IndexPatch, ValidationReport.
- Write zone: declared managed zones only.
- Evidence: explicit mode, written paths, committed SQLite transaction, post-audit path.
- Gate: validation passes; apply is explicit; deletion has snapshot and explicit confirmation.
- Failure modes: `permission_blocked`, `partial_output`, `schema_mismatch`, `regression_detected`, `security_blocked`.
- Retry: one forward-fix only before acceptance; database lock retry is bounded.
- Stop: deletion lacks confirmation/snapshot, audit error, source-state mismatch, or write-zone escape.
- Handoff: PublishReport and evidence bundle.

Never delete a raw source. Beta may clean generated state only after the user removes the source and confirms the snapshotted plan.
