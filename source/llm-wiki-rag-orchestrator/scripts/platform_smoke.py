#!/usr/bin/env python3
"""Static/runtime smoke for the declared local Python profile."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    required = [root / "SKILL.md", root / "scripts" / "llm_wiki_rag.py", root / "references" / "operations-runbook.md"]
    help_run = subprocess.run([sys.executable, str(root / "scripts" / "llm_wiki_rag.py"), "--help"], capture_output=True, text=True, check=False)
    report = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "profile": "local-python-sqlite",
        "files_present": all(path.exists() for path in required),
        "cli_help_exit_code": help_run.returncode,
        "commands_present": all(name in help_run.stdout for name in ("update", "rollback", "migrate", "query")),
    }
    report["passed"] = report["files_present"] and report["cli_help_exit_code"] == 0 and report["commands_present"]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
