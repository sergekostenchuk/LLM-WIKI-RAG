#!/usr/bin/env python3
"""Operational safety layer for LLM-WIKI-RAG Production 1.0."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class OperationalBlocked(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ProjectLock:
    def __init__(self, project: Path, command: str, stale_after_seconds: int = 3600) -> None:
        self.path = project / ".llm-wiki-rag" / "operation.lock"
        self.command = command
        self.stale_after_seconds = stale_after_seconds
        self.acquired = False

    @staticmethod
    def _pid_error_indicates_missing(error: OSError) -> bool:
        return isinstance(error, ProcessLookupError) or getattr(error, "winerror", None) == 87

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            # Windows reports ERROR_INVALID_PARAMETER (87), rather than
            # ProcessLookupError, when the PID does not exist.
            if ProjectLock._pid_error_indicates_missing(exc):
                return False
            # Unknown platform errors must not cause an unsafe lock takeover.
            return True
        return True

    def _recover_stale(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            age = time.time() - float(data.get("created_epoch", 0))
            pid = int(data.get("pid", -1))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        if age <= self.stale_after_seconds or self._pid_alive(pid):
            return False
        stale = self.path.with_name(f"operation.lock.stale.{int(time.time())}")
        self.path.replace(stale)
        return True

    def __enter__(self) -> "ProjectLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"pid": os.getpid(), "command": self.command, "created_at": utc_now(), "created_epoch": time.time()},
            sort_keys=True,
        ) + "\n"
        for attempt in range(2):
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                if attempt == 0 and self._recover_stale():
                    continue
                raise OperationalBlocked(f"another operation holds the project lock: {self.path}")
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
            self.acquired = True
            return self
        raise OperationalBlocked("unable to acquire project lock")

    def __exit__(self, exc_type, exc, traceback) -> None:  # type: ignore[no-untyped-def]
        if self.acquired:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if int(data.get("pid", -1)) == os.getpid():
                    self.path.unlink()
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                pass
            self.acquired = False


@dataclass(frozen=True)
class Finding:
    finding_type: str
    severity: str
    line: int
    fingerprint: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "finding_type": self.finding_type,
            "severity": self.severity,
            "line": self.line,
            "fingerprint": self.fingerprint,
            "message": self.message,
        }


SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("generic_bearer_token", re.compile(r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{16,}")),
    ("credential_assignment", re.compile(r"(?i)\b(?:api[_-]?key|secret|password|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_./+-]{12,}")),
]
PII_PATTERNS = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone", re.compile(r"(?<!\d)\+?\d[\d ()-]{8,}\d(?!\d)")),
]


def _fingerprint(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:16]


def scan_sensitive_text(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(line):
                findings.append(Finding(kind, "block", line_number, _fingerprint(kind, match.group(0)), "Potential secret detected; value redacted."))
        for kind, pattern in PII_PATTERNS:
            for match in pattern.finditer(line):
                findings.append(Finding(kind, "review", line_number, _fingerprint(kind, match.group(0)), "Potential personal data detected; value redacted."))
    return findings


def enforce_budgets(records: list[dict[str, Any]], config: dict[str, Any]) -> None:
    budgets = config.get("budgets") or {}
    max_sources = int(budgets.get("max_sources_per_run", 1000))
    max_bytes = int(budgets.get("max_total_source_bytes_per_run", 100 * 1024 * 1024))
    if len(records) > max_sources:
        raise OperationalBlocked(f"source budget exceeded: {len(records)} > {max_sources}")
    total_bytes = sum(int(record.get("size_bytes", 0)) for record in records)
    if total_bytes > max_bytes:
        raise OperationalBlocked(f"source byte budget exceeded: {total_bytes} > {max_bytes}")


def approval_packet(project: Path, run_id: str, findings: list[dict[str, Any]], reason: str) -> Path:
    path = project / "agent-workspace" / "runs" / run_id / "approval-required.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    packet = {
        "run_id": run_id,
        "status": "human_approval_required",
        "reason": reason,
        "findings": findings,
        "secret_values_included": False,
        "created_at": utc_now(),
    }
    path.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def emit_event(project: Path, event: dict[str, Any]) -> Path:
    path = project / "agent-workspace" / "logs" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = dict(event)
    sanitized.setdefault("timestamp", utc_now())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(sanitized, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def update_metrics(project: Path, command: str, status: str, duration_seconds: float) -> Path:
    path = project / ".llm-wiki-rag" / "metrics.json"
    data: dict[str, Any] = {"schema_version": 1, "commands": {}, "updated_at": utc_now()}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    commands = data.setdefault("commands", {})
    item = commands.setdefault(command, {"runs": 0, "accepted": 0, "blocked_or_failed": 0, "duration_seconds_total": 0.0})
    item["runs"] += 1
    item["accepted" if status in {"accepted", "planned"} else "blocked_or_failed"] += 1
    item["duration_seconds_total"] = round(float(item["duration_seconds_total"]) + duration_seconds, 4)
    data["updated_at"] = utc_now()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
