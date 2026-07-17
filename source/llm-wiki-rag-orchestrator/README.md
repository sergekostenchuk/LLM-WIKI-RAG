# LLM-WIKI-RAG Knowledge Maintainer — Production 1.0

This source folder contains an orchestrator skill, worker contracts, deterministic scripts, fixtures, and policies for a local hybrid Wiki/RAG knowledge project.

Quick smoke test:

```bash
python3 scripts/smoke_test.py
python3 scripts/beta_smoke_test.py
python3 scripts/retrieval_regression.py
```

Initialize a knowledge project:

```bash
python3 scripts/llm_wiki_rag.py init --project /absolute/path/to/knowledge-project
```

Preview before applying:

```bash
python3 scripts/llm_wiki_rag.py update --project /absolute/path/to/knowledge-project
python3 scripts/llm_wiki_rag.py update --project /absolute/path/to/knowledge-project --apply
python3 scripts/llm_wiki_rag.py audit --project /absolute/path/to/knowledge-project
```

Production adds staging, snapshots, exact-content rename detection, confirmed derived-state cleanup, rebuild, rollback, retrieval, locks, budgets, security gates, migrations, telemetry, health checks, scheduling adapters, independent validation, and operational runbooks.

Production-ready profile: local Python+SQLite with `hashing-v1`. The external HTTPS embedding profile remains conditional until a concrete endpoint, model, dimensions, credentials boundary, and retrieval regression are verified. Semantic conflicts remain human-reviewed.
