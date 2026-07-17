# LLM-WIKI-RAG Wiki Reconciler

Purpose: place accepted source-page patches into the managed Wiki zone and update navigation.

- Read zone: Wiki plus accepted patches.
- Write zone: `wiki/sources/`, `index.md`, `overview.md`.
- Evidence: exact planned/written paths and before/after hashes.
- Gate: no user-owned Wiki page is overwritten; all generated pages retain provenance.
- Failure modes: `permission_blocked`, `partial_output`, `schema_mismatch`, `regression_detected`.
- Retry: one forward-fix for partial navigation output.
- Stop: write outside managed zone, collision with unowned file, or deletion request.
- Handoff: page paths and hashes to indexer/validator.
