#!/usr/bin/env python3
"""End-to-end Beta 0.2 lifecycle checks."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "llm_wiki_rag.py"


def run(project: Path, command: str, *extra: str, expected: int = 0) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), command, "--project", str(project), *extra],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"{command} {' '.join(extra)} returned {result.returncode}, expected {expected}\n{result.stdout}\n{result.stderr}"
        )
    return json.loads(result.stdout)


def main() -> int:
    checks: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="llm-wiki-rag-beta-") as temp:
        project = Path(temp) / "knowledge-project"
        run(project, "init")
        raw = project / "raw" / "sources"
        (raw / "safety.md").write_text(
            "# Provenance safety\n\nEvery generated claim needs source provenance and audit evidence.\n",
            encoding="utf-8",
        )
        original_rename_content = "# Glacier archive\n\nImmutable glacier records use cryogenic catalog identifiers.\n"
        (raw / "archive.txt").write_text(original_rename_content, encoding="utf-8")
        initial = run(project, "update", "--apply")
        original_id = next(item["source_id"] for item in initial["changeset"]["added"] if item["relative_path"].endswith("archive.txt"))
        checks.append({"name": "initial_snapshot", "passed": bool(initial.get("snapshot_id"))})
        checks.append({"name": "staging_published", "passed": Path(initial["staging_path"], "status.json").exists()})

        (raw / "archive.txt").rename(raw / "glacier-archive.txt")
        rename_plan = run(project, "update")
        checks.append({"name": "rename_detected", "passed": len(rename_plan["changeset"]["renamed"]) == 1})
        renamed = run(project, "update", "--apply")
        renamed_item = renamed["changeset"]["renamed"][0]
        checks.append({"name": "rename_identity_preserved", "passed": renamed_item["source_id"] == original_id})
        status = run(project, "status")
        checks.append({"name": "rename_not_delete", "passed": status["counts"]["deleted"] == 0 and status["counts"]["known_sources"] == 2})

        query = run(project, "query", "--text", "cryogenic glacier catalog", "--limit", "2")
        checks.append({"name": "retrieval_top_source", "passed": bool(query["results"]) and query["results"][0]["relative_path"].endswith("glacier-archive.txt")})

        (raw / "glacier-archive.txt").unlink()
        blocked = run(project, "update", "--apply", expected=2)
        checks.append({"name": "deletion_needs_confirmation", "passed": blocked["status"] == "blocked"})
        deleted = run(project, "delete", "--source", "glacier-archive.txt", "--apply", "--confirm")
        delete_snapshot = deleted["snapshot_id"]
        checks.append({"name": "confirmed_delete", "passed": deleted["status"] == "accepted"})
        checks.append({"name": "delete_snapshot", "passed": bool(delete_snapshot)})
        checks.append({"name": "derived_delete_only", "passed": run(project, "status")["counts"]["known_sources"] == 1})

        (raw / "glacier-archive.txt").write_text(original_rename_content, encoding="utf-8")
        rollback = run(project, "rollback", "--snapshot", delete_snapshot, "--confirm")
        checks.append({"name": "rollback_accepted", "passed": rollback["status"] == "accepted"})
        status_after_rollback = run(project, "status")
        snapshots_after_rollback = run(project, "snapshots")
        checks.append({"name": "rollback_restores_state", "passed": status_after_rollback["counts"]["known_sources"] == 2})
        checks.append({
            "name": "rollback_snapshot_count_consistent",
            "passed": status_after_rollback["counts"]["snapshots"] == snapshots_after_rollback["count"],
        })

        rebuild_plan = run(project, "rebuild")
        checks.append({"name": "rebuild_dry_run", "passed": rebuild_plan["status"] == "planned" and rebuild_plan["source_count"] == 2})
        rebuilt = run(project, "rebuild", "--apply")
        checks.append({"name": "rebuild_snapshot", "passed": rebuilt["status"] == "accepted" and bool(rebuilt.get("snapshot_id"))})
        checks.append({"name": "rebuild_audit", "passed": rebuilt["post_audit"]["passed"] is True})
        safety_path = raw / "safety.md"
        safety_original = safety_path.read_text(encoding="utf-8")
        safety_path.write_text("# Changed after snapshot\n", encoding="utf-8")
        mismatch = run(project, "rollback", "--snapshot", rebuilt["snapshot_id"], "--confirm", expected=2)
        checks.append({"name": "rollback_hash_mismatch_blocked", "passed": mismatch["status"] == "blocked"})
        safety_path.write_text(safety_original, encoding="utf-8")

        snapshots = run(project, "snapshots")
        checks.append({"name": "snapshot_inventory", "passed": snapshots["count"] >= 4})
        final_audit = run(project, "audit")
        checks.append({"name": "final_audit", "passed": final_audit["passed"] is True})

        unsafe = Path(temp) / "unsafe-project"
        outside = Path(temp) / "outside-wiki"
        outside.mkdir()
        run(unsafe, "init")
        (unsafe / "wiki" / "sources").rmdir()
        (unsafe / "wiki" / "sources").symlink_to(outside, target_is_directory=True)
        (unsafe / "raw" / "sources" / "source.md").write_text("# Symlink boundary\n", encoding="utf-8")
        symlink_block = run(unsafe, "update", "--apply", expected=2)
        checks.append({"name": "managed_symlink_blocked", "passed": symlink_block["status"] == "blocked" and not any(outside.iterdir())})

        passed = all(bool(item["passed"]) for item in checks)
        print(json.dumps({"suite": "beta-0.2-smoke", "passed": passed, "checks": checks}, indent=2, sort_keys=True))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
