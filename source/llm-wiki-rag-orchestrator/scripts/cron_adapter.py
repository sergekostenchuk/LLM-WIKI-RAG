#!/usr/bin/env python3
"""Generate, but never silently install, a cron entry."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an LLM-WIKI-RAG cron plan")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--schedule", default="*/15 * * * *")
    parser.add_argument("--apply-updates", action="store_true")
    args = parser.parse_args()
    cli = Path(__file__).resolve().parent / "llm_wiki_rag.py"
    project = args.project.expanduser().resolve()
    log = project / "agent-workspace" / "logs" / "cron.log"
    command = [sys.executable, str(cli), "update", "--project", str(project)]
    if args.apply_updates:
        command.append("--apply")
    shell_command = " ".join(shlex.quote(value) for value in command)
    cron_line = f"{args.schedule} {shell_command} >> {shlex.quote(str(log))} 2>&1"
    print(json.dumps({"status": "planned", "installed": False, "cron_line": cron_line, "deletions_enabled": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
