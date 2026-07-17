#!/usr/bin/env python3
"""Self-contained deterministic release check for the production profile."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def run(command: list[str], cwd: Path) -> dict:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return {
        "command": command,
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-path", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    skill = args.skill_path.resolve()
    scripts = skill / "scripts"
    syntax_errors = []
    for path in sorted(scripts.glob("*.py")):
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except SyntaxError as exc:
            syntax_errors.append({"path": str(path), "error": str(exc)})
    json_errors = []
    for path in sorted(skill.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            json_errors.append({"path": str(path), "error": str(exc)})
    checks = [
        run([sys.executable, "-m", "unittest", "discover", "-s", str(skill / "tests")], skill),
        run([sys.executable, str(scripts / "smoke_test.py")], skill),
        run([sys.executable, str(scripts / "beta_smoke_test.py")], skill),
        run([sys.executable, str(scripts / "production_smoke_test.py")], skill),
        run([sys.executable, str(scripts / "retrieval_regression.py")], skill),
        run([sys.executable, str(scripts / "platform_smoke.py")], skill),
    ]
    passed = not syntax_errors and not json_errors and all(item["passed"] for item in checks)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": "local-python-sqlite",
        "passed": passed,
        "syntax_errors": syntax_errors,
        "json_errors": json_errors,
        "checks": checks,
    }
    output = args.output
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "check_count": len(checks), "syntax_errors": len(syntax_errors), "json_errors": len(json_errors)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
