#!/usr/bin/env python3
"""Grade actual independent production behavioral outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def match(assertion: dict[str, Any], output: str) -> tuple[bool, str]:
    lower = output.lower()
    all_terms = [str(value).lower() for value in assertion.get("all_terms", [])]
    any_terms = [str(value).lower() for value in assertion.get("any_terms", [])]
    also_any = [str(value).lower() for value in assertion.get("also_any_terms", [])]
    passed = all(term in lower for term in all_terms)
    if any_terms:
        passed = passed and any(term in lower for term in any_terms)
    if also_any:
        passed = passed and any(term in lower for term in also_any)
    return passed, f"all={all_terms}; any={any_terms}; also_any={also_any}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    manifest = json.loads((workspace / "behavioral-run-manifest.json").read_text(encoding="utf-8"))
    results = []
    for run in manifest["runs"]:
        run_dir = Path(run["run_dir"])
        eval_dir = run_dir.parents[1]
        metadata = json.loads((eval_dir / "eval_metadata.json").read_text(encoding="utf-8"))
        output_path = run_dir / "outputs" / "result.md"
        actual = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        assertions = []
        for assertion in metadata["assertions"]:
            passed, evidence = match(assertion, actual)
            assertions.append({"id": assertion["id"], "text": assertion["text"], "passed": passed, "evidence": evidence})
        passed_count = sum(1 for item in assertions if item["passed"])
        grading = {
            "runtime_mode": "codex-cli-independent",
            "actual_output_recorded": output_path.exists(),
            "configuration": run["configuration"],
            "expectations": assertions,
            "summary": {"passed": passed_count, "failed": len(assertions) - passed_count, "total": len(assertions), "pass_rate": passed_count / len(assertions)},
        }
        (run_dir / "grading.json").write_text(json.dumps(grading, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        results.append({"eval_key": metadata["eval_key"], "configuration": run["configuration"], **grading["summary"]})
    with_skill = [item for item in results if item["configuration"] == "with_skill"]
    baseline = [item for item in results if item["configuration"] == "without_skill"]
    with_rate = sum(item["passed"] for item in with_skill) / sum(item["total"] for item in with_skill)
    baseline_rate = sum(item["passed"] for item in baseline) / sum(item["total"] for item in baseline)
    report = {
        "runtime_mode": "behavioral_recorded_outputs",
        "actual_outputs_required": True,
        "with_skill_pass_rate": with_rate,
        "baseline_pass_rate": baseline_rate,
        "delta": with_rate - baseline_rate,
        "with_skill_gate_passed": with_rate == 1.0,
        "results": results,
    }
    (workspace / "behavioral-eval-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["with_skill_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
