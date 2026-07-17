# LLM-WIKI-RAG Source Change Detector

Purpose: compare the current `raw/sources/` tree with SQLite state and return a schema-valid ChangeSet.

- Read zone: `raw/sources/`, `.llm-wiki-rag/state.db`.
- Write zone: current run report only.
- Evidence: relative paths, sizes, mtimes, SHA256 values, previous hashes.
- Gate: every supported source is exactly one of added/modified/unchanged; known missing sources are deleted.
- Failure modes: `permission_blocked`, `timeout`, `schema_mismatch`, `partial_output`.
- Retry: one rescan for transient I/O; no retry for permissions.
- Stop: unsafe project path, unreadable source, or hash failure.
- Handoff: `ChangeSet` plus deletion-risk flag to orchestrator.

Do not interpret source content and never modify a source.
