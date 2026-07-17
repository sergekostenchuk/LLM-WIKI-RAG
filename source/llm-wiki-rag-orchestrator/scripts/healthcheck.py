#!/usr/bin/env python3
"""Operational health check suitable for cron and alerting."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-WIKI-RAG health check")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--max-metrics-age-seconds", type=int, default=3600)
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    cli = Path(__file__).resolve().parent / "llm_wiki_rag.py"
    audit = subprocess.run([sys.executable, str(cli), "audit", "--project", str(project)], capture_output=True, text=True, check=False)
    metrics_path = project / ".llm-wiki-rag" / "metrics.json"
    reasons = []
    if audit.returncode:
        reasons.append("audit_failed")
    if not metrics_path.exists():
        reasons.append("metrics_missing")
    else:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(metrics["updated_at"])
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        if age > args.max_metrics_age_seconds:
            reasons.append("metrics_stale")
    report = {"status": "healthy" if not reasons else "unhealthy", "reasons": reasons, "audit_exit_code": audit.returncode}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not reasons else 3


if __name__ == "__main__":
    raise SystemExit(main())
