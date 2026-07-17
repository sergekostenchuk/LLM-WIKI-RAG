# Contributing

Thank you for improving LLM-WIKI-RAG.

## Development setup

Requirements: Node.js 18+, npm 9+, and Python 3.11+.

```bash
npm install
npm test
npm run pack:dry-run
```

## Pull requests

1. Open an issue for substantial behavior or schema changes.
2. Keep raw-source immutability, dry-run defaults, explicit deletion confirmation, and rollback hash verification intact.
3. Add a regression test for behavioral fixes.
4. Update both English and Russian user documentation when the public interface changes.
5. Run the complete release check and inspect the npm tarball.
6. Use a focused commit and explain operational risks in the pull request.

## Code style

- Prefer Python standard-library solutions in the production runtime.
- Keep deterministic state transitions separate from optional LLM reasoning.
- Emit machine-readable JSON from CLI commands.
- Never log secrets or include source content in telemetry unless explicitly documented.
- Use filesystem-safe, cross-platform paths.

## Licensing contributions

Unless explicitly stated otherwise, intentionally submitted contributions are provided under Apache-2.0 as described in Section 5 of the license.
