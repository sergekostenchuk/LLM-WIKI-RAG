# LLM-WIKI-RAG RAG Indexer

Purpose: chunk normalized text and update versioned local vector records.

- Read zone: accepted normalized documents.
- Write zone: SQLite `chunks` table and vector metadata.
- Evidence: chunk IDs, source IDs/hashes, provider, dimensions, counts.
- Gate: every chunk maps to the active source version; replacement occurs transactionally.
- Failure modes: `tool_unavailable`, `schema_mismatch`, `partial_output`, `regression_detected`.
- Retry: one transaction retry for transient database lock.
- Stop: provider/dimension drift, orphan source, or transaction failure.
- Handoff: IndexPatch summary to validator.

Label `hashing-v1` as a deterministic MVP baseline, not semantic embedding.
