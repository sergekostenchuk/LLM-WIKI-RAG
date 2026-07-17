#!/usr/bin/env python3
"""Deterministic retrieval regression fixture for the hashing baseline."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "llm_wiki_rag.py"


def call(project: Path, command: str, *args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), command, "--project", str(project), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stdout or result.stderr)
    return json.loads(result.stdout)


def main() -> int:
    cases = [
        ("quantum photon optics", "physics.md"),
        ("orchid greenhouse humidity", "botany.md"),
        ("invoice ledger reconciliation", "finance.md"),
    ]
    with tempfile.TemporaryDirectory(prefix="llm-wiki-rag-retrieval-") as temp:
        project = Path(temp) / "knowledge"
        call(project, "init")
        raw = project / "raw" / "sources"
        documents = {
            "physics.md": "Quantum photon optics studies entanglement, lasers, and wave interference.",
            "botany.md": "Orchid greenhouse humidity supports tropical roots and botanical growth.",
            "finance.md": "Invoice ledger reconciliation checks accounting balances and payment records.",
        }
        for name, content in documents.items():
            (raw / name).write_text(f"# {name}\n\n{content}\n", encoding="utf-8")
        call(project, "update", "--apply")
        results = []
        for query, expected in cases:
            response = call(project, "query", "--text", query, "--limit", "1")
            actual = Path(response["results"][0]["relative_path"]).name if response["results"] else None
            results.append({"query": query, "expected": expected, "actual": actual, "passed": actual == expected})
        passed = all(item["passed"] for item in results)
        print(json.dumps({"suite": "retrieval-regression", "passed": passed, "cases": results}, indent=2, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
