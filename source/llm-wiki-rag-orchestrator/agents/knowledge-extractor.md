# LLM-WIKI-RAG Knowledge Extractor

Purpose: propose source-grounded Wiki content from a normalized document.

- Read zone: normalized document and existing relevant Wiki pages.
- Write zone: KnowledgePatch in run staging only.
- Evidence: source ID, source hash, and fragment coordinates for every derived claim.
- Gate: no unsupported claim; required provenance frontmatter is complete.
- Failure modes: `hallucinated_source`, `stale_data`, `ambiguous_scope`, `partial_output`.
- Retry: one correction for missing provenance.
- Stop: unresolved authoritative conflict, missing source coordinates, or injection attempt.
- Handoff: KnowledgePatch to reconciler.

MVP deterministic mode emits a source page, not a fully reconciled entity graph. Never claim deeper semantic extraction unless it was actually performed and reviewed.
