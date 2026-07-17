# Commands

Set the skill root explicitly:

```bash
python3 <skill>/scripts/llm_wiki_rag.py init --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py update --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py update --project /absolute/project/path --apply
python3 <skill>/scripts/llm_wiki_rag.py update --project /absolute/project/path --apply --confirm-deletions
python3 <skill>/scripts/llm_wiki_rag.py delete --project /absolute/project/path --source raw/sources/example.md
python3 <skill>/scripts/llm_wiki_rag.py delete --project /absolute/project/path --source raw/sources/example.md --apply --confirm
python3 <skill>/scripts/llm_wiki_rag.py audit --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py status --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py query --project /absolute/project/path --text "question"
python3 <skill>/scripts/llm_wiki_rag.py rebuild --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py rebuild --project /absolute/project/path --apply
python3 <skill>/scripts/llm_wiki_rag.py snapshots --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py rollback --project /absolute/project/path --snapshot <id> --confirm
python3 <skill>/scripts/llm_wiki_rag.py conflicts --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py migrate --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py migrate --project /absolute/project/path --apply
python3 <skill>/scripts/watcher.py --project /absolute/project/path --once
python3 <skill>/scripts/cron_adapter.py --project /absolute/project/path
python3 <skill>/scripts/independent_validator.py --project /absolute/project/path
python3 <skill>/scripts/healthcheck.py --project /absolute/project/path
python3 <skill>/scripts/llm_wiki_rag.py approve --project /absolute/project/path --fingerprint <16-hex> --scope <scope> --confirm
```

All mutating commands emit JSON and write a matching report. `init` creates missing files only. `update`, `delete`, and `rebuild` are dry-run unless `--apply` is supplied. Bulk cleanup through `update` additionally requires `--confirm-deletions`; targeted `delete` requires `--confirm`, never removes a raw source, and refuses a scope mismatch. Rollback requires `--confirm` and refuses when current raw hashes do not match the target snapshot.

Exit codes:

- `0`: completed and accepted for the requested mode;
- `2`: blocked by scope, deletion, parser, or safety rule;
- `3`: audit or schema validation failed;
- `4`: unexpected internal failure.
