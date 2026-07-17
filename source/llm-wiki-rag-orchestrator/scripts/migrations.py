#!/usr/bin/env python3
"""Explicit, backed-up SQLite schema migrations."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LATEST_SCHEMA_VERSION = 2


def current_version(database: Path) -> int:
    conn = sqlite3.connect(database)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def migration_plan(database: Path) -> dict[str, Any]:
    current = current_version(database)
    return {
        "current_version": current,
        "target_version": LATEST_SCHEMA_VERSION,
        "pending": list(range(current + 1, LATEST_SCHEMA_VERSION + 1)),
        "destructive": False,
    }


def apply_migrations(project: Path) -> dict[str, Any]:
    database = project / ".llm-wiki-rag" / "state.db"
    plan = migration_plan(database)
    if plan["current_version"] == LATEST_SCHEMA_VERSION:
        return {**plan, "status": "unchanged", "backup_path": None}
    if plan["current_version"] != 1:
        raise RuntimeError(f"unsupported migration source version: {plan['current_version']}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = project / ".llm-wiki-rag" / "migration-backups" / f"state-v1-{timestamp}.db"
    backup.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(database)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    conn = sqlite3.connect(database)
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    backup_path TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    evidence_path TEXT NOT NULL
                );
                """
            )
            applied_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            conn.execute("INSERT OR REPLACE INTO schema_migrations(version,applied_at,backup_path) VALUES(?,?,?)", (2, applied_at, str(backup)))
            conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    except Exception:
        conn.close()
        shutil.copy2(backup, database)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
    report = {**plan, "status": "migrated", "backup_path": str(backup)}
    report_path = backup.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
