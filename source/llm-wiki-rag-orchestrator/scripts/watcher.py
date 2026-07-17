#!/usr/bin/env python3
"""Polling watcher adapter. Dry-run by default; finite iterations are testable."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


CLI = Path(__file__).resolve().parent / "llm_wiki_rag.py"


def tree_signature(project: Path) -> str:
    digest = hashlib.sha256()
    root = project / "raw" / "sources"
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        stat = path.stat()
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


def invoke(project: Path, apply: bool) -> tuple[int, dict]:
    command = [sys.executable, str(CLI), "update", "--project", str(project)]
    if apply:
        command.append("--apply")
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"status": "failed", "failure_mode": "partial_output", "message": "watcher child returned invalid JSON"}
    return result.returncode, payload


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-WIKI-RAG polling watcher")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--iterations", type=int, default=0, help="0 means continuous")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Apply non-destructive updates; deletions still block")
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    previous = ""
    iteration = 0
    while True:
        signature = tree_signature(project)
        if signature != previous:
            code, payload = invoke(project, args.apply)
            print(json.dumps({"event": "source_tree_changed", "iteration": iteration, "child_exit_code": code, "result": payload}, ensure_ascii=False, sort_keys=True), flush=True)
            if code not in {0, 2}:
                return code
            previous = signature
        iteration += 1
        if args.once or (args.iterations and iteration >= args.iterations):
            return 0
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
