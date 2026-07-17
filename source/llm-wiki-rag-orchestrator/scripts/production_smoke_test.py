#!/usr/bin/env python3
"""Production 1.0 operational and security smoke suite."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CLI = SCRIPTS / "llm_wiki_rag.py"


def run_script(script: Path, *args: str, expected: int = 0) -> dict:
    result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, check=False)
    if result.returncode != expected:
        raise AssertionError(f"{script.name} returned {result.returncode}, expected {expected}\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout.splitlines()[-1] if script.name == "watcher.py" else result.stdout)


def run(project: Path, command: str, *args: str, expected: int = 0) -> dict:
    return run_script(CLI, command, "--project", str(project), *args, expected=expected)


def fingerprint(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:16]


def main() -> int:
    checks: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="llm-wiki-rag-production-") as temp:
        root = Path(temp)
        project = root / "production-project"
        run(project, "init")
        raw = project / "raw" / "sources"
        (raw / "operations.md").write_text("# Operations\n\nHealth checks and rollback protect service continuity.\n", encoding="utf-8")
        applied = run(project, "update", "--apply")
        checks.append({"name": "production_apply", "passed": applied["status"] == "accepted"})
        checks.append({"name": "telemetry_event_log", "passed": (project / "agent-workspace" / "logs" / "events.jsonl").exists()})
        checks.append({"name": "metrics_created", "passed": (project / ".llm-wiki-rag" / "metrics.json").exists()})

        lock_path = project / ".llm-wiki-rag" / "operation.lock"
        lock_path.write_text(json.dumps({"pid": os.getpid(), "command": "holder", "created_epoch": time.time()}) + "\n", encoding="utf-8")
        locked = run(project, "update", "--apply", expected=2)
        checks.append({"name": "concurrent_lock_blocked", "passed": locked["status"] == "blocked"})
        lock_path.unlink()
        lock_path.write_text(json.dumps({"pid": 99999999, "command": "stale", "created_epoch": 1}) + "\n", encoding="utf-8")
        recovered = run(project, "update", "--apply")
        checks.append({"name": "stale_lock_recovered", "passed": recovered["status"] == "accepted" and not lock_path.exists()})

        secret_project = root / "secret-project"
        run(secret_project, "init")
        secret_value = "api_key=ABCDEF1234567890SECRET"
        (secret_project / "raw" / "sources" / "secret.txt").write_text(secret_value + "\n", encoding="utf-8")
        secret_block = run(secret_project, "update", "--apply", expected=2)
        packet_path = Path(secret_block["errors"][0]["approval_packet"])
        packet_text = packet_path.read_text(encoding="utf-8")
        checks.append({"name": "secret_blocked", "passed": secret_block["status"] == "blocked"})
        checks.append({"name": "secret_redacted_in_packet", "passed": secret_value not in packet_text and "fingerprint" in packet_text})
        approved = run(
            secret_project,
            "approve",
            "--fingerprint",
            fingerprint("credential_assignment", secret_value),
            "--scope",
            "sensitive-source",
            "--confirm",
        )
        checks.append({"name": "approval_audit_record", "passed": approved["status"] == "accepted" and approved["secret_value_recorded"] is False})
        secret_approved = run(secret_project, "update", "--apply")
        checks.append({"name": "explicit_fingerprint_approval", "passed": secret_approved["status"] == "accepted"})

        budget_project = root / "budget-project"
        run(budget_project, "init")
        budget_config_path = budget_project / ".llm-wiki-rag" / "config.json"
        budget_config = json.loads(budget_config_path.read_text(encoding="utf-8"))
        budget_config["budgets"]["max_sources_per_run"] = 1
        budget_config_path.write_text(json.dumps(budget_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for name in ("one.md", "two.md"):
            (budget_project / "raw" / "sources" / name).write_text(f"# {name}\n", encoding="utf-8")
        budget_block = run(budget_project, "update", "--apply", expected=2)
        checks.append({"name": "source_budget_blocked", "passed": "budget exceeded" in budget_block["message"]})

        migration_project = root / "migration-project"
        run(migration_project, "init")
        database = migration_project / ".llm-wiki-rag" / "state.db"
        conn = sqlite3.connect(database)
        with conn:
            conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
            conn.execute("DROP TABLE schema_migrations")
            conn.execute("DROP TABLE approvals")
        conn.close()
        migration_plan = run(migration_project, "migrate")
        migrated = run(migration_project, "migrate", "--apply")
        checks.append({"name": "migration_dry_run", "passed": migration_plan["pending"] == [2]})
        checks.append({"name": "migration_backup", "passed": migrated["status"] == "migrated" and Path(migrated["backup_path"]).exists()})
        checks.append({"name": "migration_post_status", "passed": run(migration_project, "status")["status"] == "accepted"})

        watcher = run_script(SCRIPTS / "watcher.py", "--project", str(project), "--once")
        checks.append({"name": "watcher_once", "passed": watcher["event"] == "source_tree_changed"})
        cron = run_script(SCRIPTS / "cron_adapter.py", "--project", str(project))
        checks.append({"name": "cron_plan_not_installed", "passed": cron["status"] == "planned" and cron["installed"] is False})
        validator = run_script(SCRIPTS / "independent_validator.py", "--project", str(project))
        checks.append({"name": "independent_validator", "passed": validator["accepted"] is True})
        health = run_script(SCRIPTS / "healthcheck.py", "--project", str(project))
        checks.append({"name": "healthcheck_healthy", "passed": health["status"] == "healthy"})
        (project / "wiki" / "broken-production.md").write_text("[[missing-production-page]]\n", encoding="utf-8")
        unhealthy = run_script(SCRIPTS / "healthcheck.py", "--project", str(project), expected=3)
        checks.append({"name": "healthcheck_alerts", "passed": unhealthy["status"] == "unhealthy" and "audit_failed" in unhealthy["reasons"]})

        passed = all(bool(item["passed"]) for item in checks)
        print(json.dumps({"suite": "production-1.0-smoke", "passed": passed, "checks": checks}, indent=2, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
