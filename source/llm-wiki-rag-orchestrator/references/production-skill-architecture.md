# Production Skill Architecture Summary

The skill uses `SKILL.md` for routing, `references/` for policies, `scripts/` for deterministic state changes, `assets/` for templates, `agents/` for worker contracts, and `evals/` for realistic checks. Inputs, outputs, non-goals, dependencies, failure modes, evidence, retry limits, write zones, and review paths are explicit.

Production 1.0 is accepted for the declared local Python+SQLite profile after proven rollback, dependency validation, actual independent behavioral evals, sanitation, platform smoke, packaging, install dry-run, and final review. External semantic adapters remain conditional until their endpoint/model configuration is independently verified.
