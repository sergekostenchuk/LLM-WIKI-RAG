#!/usr/bin/env python3
"""Run validation in an independent process boundary."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent LLM-WIKI-RAG validator")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cli = Path(__file__).resolve().parent / "llm_wiki_rag.py"
    result = subprocess.run(
        [sys.executable, str(cli), "audit", "--project", str(args.project.expanduser().resolve())],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {"status": "failed", "passed": False, "failure_mode": "partial_output", "stderr": result.stderr[:300]}
    wrapper = {
        "validator_process": "independent_subprocess",
        "child_exit_code": result.returncode,
        "accepted": result.returncode == 0 and report.get("passed") is True,
        "audit": report,
    }
    text = json.dumps(wrapper, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if wrapper["accepted"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
