#!/usr/bin/env python3
"""End-to-end smoke test for LLM-WIKI-RAG MVP 0.1."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "llm_wiki_rag.py"
FIXTURES = ROOT / "evals" / "fixtures"


def run(project: Path, command: str, *extra: str, expected: int = 0) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), command, "--project", str(project), *extra],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"{command} {' '.join(extra)} returned {result.returncode}, expected {expected}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return json.loads(result.stdout)


def main() -> int:
    checks: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="llm-wiki-rag-smoke-") as temp:
        project = Path(temp) / "knowledge-project"
        initial = run(project, "init")
        checks.append({"name": "init", "passed": initial["status"] == "accepted"})

        raw = project / "raw" / "sources"
        shutil.copy2(FIXTURES / "source-a.md", raw / "source-a.md")
        shutil.copy2(FIXTURES / "source-b.txt", raw / "source-b.txt")
        hashes_before = {p.name: p.read_bytes() for p in raw.iterdir()}

        dry = run(project, "update")
        checks.append({"name": "dry_run_detects_two", "passed": len(dry["changeset"]["added"]) == 2})
        checks.append({"name": "dry_run_no_sources_in_db", "passed": run(project, "status")["counts"]["known_sources"] == 0})

        applied = run(project, "update", "--apply")
        checks.append({"name": "apply_accepted", "passed": applied["accepted_by_orchestrator"] is True})
        audit = run(project, "audit")
        checks.append({"name": "audit_passes", "passed": audit["passed"] is True})
        status = run(project, "status")
        checks.append({"name": "two_sources", "passed": status["counts"]["known_sources"] == 2})
        checks.append({"name": "chunks_exist", "passed": status["counts"]["chunks"] >= 2})
        checks.append({"name": "raw_unchanged", "passed": hashes_before == {p.name: p.read_bytes() for p in raw.iterdir()}})

        second = run(project, "update", "--apply")
        checks.append({"name": "idempotent", "passed": not second["changeset"]["added"] and not second["changeset"]["modified"]})

        (raw / "source-a.md").write_text("# Updated\n\nA changed fact with provenance.\n", encoding="utf-8")
        changed = run(project, "update")
        checks.append({"name": "modified_detected", "passed": len(changed["changeset"]["modified"]) == 1})
        run(project, "update", "--apply")

        (raw / "source-b.txt").unlink()
        blocked = run(project, "update", "--apply", expected=2)
        checks.append({"name": "deletion_blocked", "passed": blocked["status"] == "blocked"})

        shutil.copy2(FIXTURES / "source-b.txt", raw / "source-b.txt")
        broken = project / "wiki" / "broken.md"
        broken.write_text("# Broken\n\n[[does-not-exist]]\n", encoding="utf-8")
        broken_audit = run(project, "audit", expected=3)
        checks.append({"name": "broken_link_detected", "passed": any(e["code"] == "broken_wikilink" for e in broken_audit["errors"])})

        passed = all(bool(check["passed"]) for check in checks)
        report = {"suite": "mvp-0.1-smoke", "passed": passed, "checks": checks}
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
