#!/usr/bin/env python3
"""Safe local MVP for an LLM-WIKI-RAG knowledge project."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from vector_adapters import AdapterError, create_embedding_adapter
from migrations import LATEST_SCHEMA_VERSION, apply_migrations, migration_plan
from production_runtime import (
    OperationalBlocked,
    ProjectLock,
    approval_packet,
    emit_event,
    enforce_budgets,
    scan_sensitive_text,
    update_metrics,
)

VERSION = "1.0.1"
SCHEMA_VERSION = str(LATEST_SCHEMA_VERSION)
SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf"}
DEFAULT_CONFIG = {
    "schema_version": 1,
    "source_extensions": sorted(SUPPORTED_EXTENSIONS),
    "max_file_bytes": 10 * 1024 * 1024,
    "chunk_chars": 1200,
    "chunk_overlap_chars": 150,
    "vector_provider": "hashing-v1",
    "vector_dimensions": 128,
    "deletion_policy": "confirm_and_snapshot",
    "snapshot_retention": 20,
    "http_embedding": {
        "endpoint": "",
        "model": "",
        "token_env": "",
        "timeout_seconds": 30
    },
    "budgets": {
        "max_sources_per_run": 1000,
        "max_total_source_bytes_per_run": 104857600,
        "max_chunks_per_run": 10000,
        "max_external_embedding_calls_per_run": 1000
    },
    "security": {
        "secret_mode": "block",
        "pii_mode": "review",
        "approved_fingerprints": []
    },
    "operations": {
        "lock_stale_after_seconds": 3600,
        "watch_interval_seconds": 30
    },
}


class BlockedError(RuntimeError):
    """A safety or scope gate blocked the requested operation."""


class AuditError(RuntimeError):
    """Integrity checks failed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    unsafe = {Path("/").resolve(), Path.home().resolve()}
    if project in unsafe:
        raise BlockedError(f"unsafe project root: {project}")
    if len(project.parts) < 3:
        raise BlockedError(f"project path is too broad: {project}")
    return project


def state_path(project: Path) -> Path:
    return project / ".llm-wiki-rag" / "state.db"


def config_path(project: Path) -> Path:
    return project / ".llm-wiki-rag" / "config.json"


def load_config(project: Path) -> dict[str, Any]:
    path = config_path(project)
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise BlockedError("unsupported config schema_version")
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    configured_extensions = {str(item).lower() for item in merged["source_extensions"]}
    unsupported_extensions = configured_extensions - SUPPORTED_EXTENSIONS
    if unsupported_extensions:
        raise BlockedError(f"unsupported source extensions: {sorted(unsupported_extensions)}")
    if merged["deletion_policy"] not in {"detect_and_block", "confirm_and_snapshot"}:
        raise BlockedError("unsupported deletion_policy")
    if merged["vector_provider"] not in {"hashing-v1", "http-json-v1"}:
        raise BlockedError("unsupported vector_provider")
    if not 1 <= int(merged["vector_dimensions"]) <= 4096:
        raise BlockedError("vector_dimensions must be between 1 and 4096")
    if not 1 <= int(merged["chunk_overlap_chars"]) < int(merged["chunk_chars"]):
        raise BlockedError("chunk overlap must be positive and smaller than chunk size")
    security = merged.get("security") or {}
    if security.get("secret_mode", "block") != "block":
        raise BlockedError("production secret_mode must be block")
    if security.get("pii_mode", "review") not in {"review", "block"}:
        raise BlockedError("unsupported pii_mode")
    return merged


def connect(project: Path) -> sqlite3.Connection:
    path = state_path(project)
    if not path.exists():
        raise BlockedError("project is not initialized; run init first")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    schema = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if not schema or schema["value"] != SCHEMA_VERSION:
        conn.close()
        raise BlockedError("unsupported SQLite schema version")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            reason TEXT NOT NULL,
            run_id TEXT NOT NULL,
            path TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conflicts (
            conflict_id TEXT PRIMARY KEY,
            entity_key TEXT NOT NULL,
            source_ids_json TEXT NOT NULL,
            details_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );
        """
    )
    return conn


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                relative_path TEXT NOT NULL UNIQUE,
                content_hash TEXT NOT NULL,
                media_type TEXT NOT NULL,
                status TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                wiki_page TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                text TEXT NOT NULL,
                vector_provider TEXT NOT NULL,
                vector_dimensions INTEGER NOT NULL,
                vector_json TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES sources(source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks(source_id);
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                report_path TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                run_id TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conflicts (
                conflict_id TEXT PRIMARY KEY,
                entity_key TEXT NOT NULL,
                source_ids_json TEXT NOT NULL,
                details_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
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
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (SCHEMA_VERSION,))
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('generator_version',?)", (VERSION,))
        conn.commit()
    finally:
        conn.close()


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def ensure_managed_path(project: Path, path: Path) -> Path:
    project = project.resolve()
    lexical = Path(os.path.abspath(path))
    allowed_roots = [
        project / "wiki" / "sources",
        project / ".llm-wiki-rag",
        project / "agent-workspace" / "runs",
    ]
    allowed_files = {project / "index.md", project / "overview.md"}
    if lexical not in allowed_files and not any(lexical == root or root in lexical.parents for root in allowed_roots):
        raise BlockedError(f"write zone escape: {lexical}")
    current = project
    try:
        relative_parts = lexical.relative_to(project).parts
    except ValueError as exc:
        raise BlockedError(f"write zone escape: {lexical}") from exc
    for part in relative_parts:
        current = current / part
        if current.is_symlink():
            raise BlockedError(f"managed path contains symlink: {current}")
    return lexical


def snapshot_root(project: Path) -> Path:
    return project / ".llm-wiki-rag" / "snapshots"


def snapshot_manifest_files(project: Path) -> list[Path]:
    files = [project / "index.md", project / "overview.md"]
    wiki_sources = project / "wiki" / "sources"
    if wiki_sources.exists():
        files.extend(sorted(path for path in wiki_sources.rglob("*") if path.is_file()))
    return files


def create_snapshot(project: Path, conn: sqlite3.Connection, reason: str, run_id: str) -> dict[str, Any]:
    ensure_managed_path(project, project / "wiki" / "sources")
    ensure_managed_path(project, project / "index.md")
    ensure_managed_path(project, project / "overview.md")
    created_at = now_iso()
    snapshot_id = f"{created_at.replace(':', '').replace('+00:00', 'Z')}-{run_id[:8]}"
    root = ensure_managed_path(project, snapshot_root(project) / snapshot_id)
    root.mkdir(parents=True, exist_ok=False)
    managed = root / "managed"
    managed.mkdir()
    hashes: dict[str, str] = {}
    for source in snapshot_manifest_files(project):
        relative = source.relative_to(project)
        destination = managed / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        hashes[relative.as_posix()] = file_hash(source)
    database_copy = root / "state.db"
    backup = sqlite3.connect(database_copy)
    try:
        conn.backup(backup)
    finally:
        backup.close()
    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": created_at,
        "reason": reason,
        "run_id": run_id,
        "managed_hashes": hashes,
        "database_sha256": file_hash(database_copy),
        "generator_version": VERSION,
    }
    atomic_write(root / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    conn.execute(
        "INSERT INTO snapshots(snapshot_id,created_at,reason,run_id,path,status) VALUES(?,?,?,?,?,?)",
        (snapshot_id, created_at, reason, run_id, str(root), "available"),
    )
    return manifest


def restore_managed_files(project: Path, snapshot_dir: Path) -> None:
    managed = snapshot_dir / "managed"
    source_snapshot = managed / "wiki" / "sources"
    current_sources = ensure_managed_path(project, project / "wiki" / "sources")
    if current_sources.exists():
        shutil.rmtree(current_sources)
    current_sources.mkdir(parents=True, exist_ok=True)
    if source_snapshot.exists():
        shutil.copytree(source_snapshot, current_sources, dirs_exist_ok=True)
    for name in ("index.md", "overview.md"):
        source = managed / name
        if source.exists():
            atomic_write(ensure_managed_path(project, project / name), source.read_text(encoding="utf-8"))


def restore_database(project: Path, snapshot_dir: Path) -> None:
    source = snapshot_dir / "state.db"
    if not source.exists():
        raise BlockedError("snapshot database is missing")
    destination = ensure_managed_path(project, state_path(project))
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(destination) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    fd, temp_name = tempfile.mkstemp(prefix=".state-restore-", dir=destination.parent)
    os.close(fd)
    try:
        shutil.copy2(source, temp_name)
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def media_type(path: Path) -> str:
    return {
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
        ".pdf": "application/pdf",
    }[path.suffix.lower()]


def slugify(value: str) -> str:
    slug = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-_.").lower()
    return slug[:80] or "source"


def wiki_page_for(relative_path: str) -> str:
    sid = source_id(relative_path)
    stem = slugify(Path(relative_path).stem)
    return f"wiki/sources/{stem}-{sid}.md"


def scan_sources(project: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    root = (project / "raw" / "sources").resolve()
    if not root.exists():
        raise BlockedError("raw/sources directory is missing")
    allowed = {str(x).lower() for x in config["source_extensions"]}
    max_bytes = int(config["max_file_bytes"])
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BlockedError(f"symlink sources are not supported in MVP: {path}")
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        resolved = path.resolve()
        if root not in resolved.parents:
            raise BlockedError(f"source escaped raw/sources: {path}")
        size = path.stat().st_size
        if size > max_bytes:
            raise BlockedError(f"source exceeds max_file_bytes: {path}")
        rel = path.relative_to(project).as_posix()
        records.append(
            {
                "source_id": source_id(rel),
                "relative_path": rel,
                "absolute_path": str(path),
                "content_hash": file_hash(path),
                "size_bytes": size,
                "media_type": media_type(path),
                "wiki_page": wiki_page_for(rel),
            }
        )
    return records


def current_sources(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT * FROM sources WHERE status='active'").fetchall()
    return {row["relative_path"]: dict(row) for row in rows}


def build_changeset(scanned: list[dict[str, Any]], known: dict[str, dict[str, Any]], run_id: str) -> dict[str, Any]:
    by_path = {record["relative_path"]: record for record in scanned}
    added = [record for path, record in by_path.items() if path not in known]
    modified = [record for path, record in by_path.items() if path in known and record["content_hash"] != known[path]["content_hash"]]
    unchanged = [record for path, record in by_path.items() if path in known and record["content_hash"] == known[path]["content_hash"]]
    deleted = [
        {key: row[key] for key in ("source_id", "relative_path", "content_hash", "media_type", "wiki_page")}
        for path, row in known.items()
        if path not in by_path
    ]
    renamed: list[dict[str, Any]] = []
    added_by_hash: dict[str, list[dict[str, Any]]] = {}
    deleted_by_hash: dict[str, list[dict[str, Any]]] = {}
    for record in added:
        added_by_hash.setdefault(record["content_hash"], []).append(record)
    for record in deleted:
        deleted_by_hash.setdefault(record["content_hash"], []).append(record)
    paired_added: set[str] = set()
    paired_deleted: set[str] = set()
    for content_hash in sorted(set(added_by_hash) & set(deleted_by_hash)):
        new_matches = added_by_hash[content_hash]
        old_matches = deleted_by_hash[content_hash]
        if len(new_matches) != 1 or len(old_matches) != 1:
            continue
        new_record = dict(new_matches[0])
        old_record = old_matches[0]
        new_record["source_id"] = old_record["source_id"]
        new_record["wiki_page"] = old_record["wiki_page"]
        renamed.append(
            {
                "source_id": old_record["source_id"],
                "from_path": old_record["relative_path"],
                "to_path": new_record["relative_path"],
                "content_hash": content_hash,
                "wiki_page": old_record["wiki_page"],
                "record": new_record,
            }
        )
        paired_added.add(new_matches[0]["relative_path"])
        paired_deleted.add(old_record["relative_path"])
    added = [record for record in added if record["relative_path"] not in paired_added]
    deleted = [record for record in deleted if record["relative_path"] not in paired_deleted]
    return {
        "run_id": run_id,
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "renamed": renamed,
        "unchanged": unchanged,
        "requires_approval": [item["relative_path"] for item in deleted],
    }


def extract_text(record: dict[str, Any]) -> tuple[str, str]:
    path = Path(record["absolute_path"])
    if path.suffix.lower() == ".pdf":
        tool = shutil.which("pdftotext")
        if not tool:
            raise BlockedError(f"tool_unavailable: pdftotext is required for {path}")
        result = subprocess.run([tool, "-layout", str(path), "-"], capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            message = result.stderr.strip()[:300]
            raise BlockedError(f"partial_output: pdftotext failed for {path}: {message}")
        text = result.stdout
        parser = "pdftotext"
    else:
        text = path.read_text(encoding="utf-8")
        parser = "utf-8"
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
    return normalized, parser


def extract_and_security_gate(
    project: Path,
    run_id: str,
    records: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[list[tuple[dict[str, Any], str, str]], list[dict[str, Any]], Path | None]:
    try:
        enforce_budgets(records, config)
    except OperationalBlocked as exc:
        raise BlockedError(str(exc)) from exc
    extracted: list[tuple[dict[str, Any], str, str]] = []
    all_findings: list[dict[str, Any]] = []
    approved = set(str(value) for value in (config.get("security") or {}).get("approved_fingerprints", []))
    pii_mode = (config.get("security") or {}).get("pii_mode", "review")
    blocking: list[dict[str, Any]] = []
    for record in records:
        text, parser_name = extract_text(record)
        extracted.append((record, parser_name, text))
        for finding in scan_sensitive_text(text):
            item = finding.as_dict()
            item["source_path"] = record["relative_path"]
            item["approved"] = finding.fingerprint in approved
            all_findings.append(item)
            if not item["approved"] and (finding.severity == "block" or pii_mode == "block"):
                blocking.append(item)
    packet = approval_packet(project, run_id, blocking, "sensitive_content") if blocking else None
    return extracted, all_findings, packet


def enforce_chunk_budget(extracted: list[tuple[dict[str, Any], str, str]], config: dict[str, Any]) -> int:
    total = sum(
        len(chunk_text(text, int(config["chunk_chars"]), int(config["chunk_overlap_chars"])))
        for _record, _parser, text in extracted
    )
    budgets = config.get("budgets") or {}
    max_chunks = int(budgets.get("max_chunks_per_run", 10000))
    if total > max_chunks:
        raise BlockedError(f"chunk budget exceeded: {total} > {max_chunks}")
    if config["vector_provider"] == "http-json-v1":
        max_calls = int(budgets.get("max_external_embedding_calls_per_run", 1000))
        if total > max_calls:
            raise BlockedError(f"external embedding call budget exceeded: {total} > {max_calls}")
    return total


def fence_source(text: str) -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}text\n{text.rstrip()}\n{fence}\n"


def render_source_page(record: dict[str, Any], text: str, generated_at: str) -> str:
    title = Path(record["relative_path"]).name
    return (
        "---\n"
        f"source_id: \"{record['source_id']}\"\n"
        f"source_path: \"{record['relative_path']}\"\n"
        f"source_hash: \"{record['content_hash']}\"\n"
        f"generated_at: \"{generated_at}\"\n"
        "status: \"active\"\n"
        f"generator_version: \"{VERSION}\"\n"
        "---\n\n"
        f"# {title}\n\n"
        "This generated source page preserves the normalized source content and provenance. "
        "Semantic entity reconciliation is deferred to a reviewed LLM worker.\n\n"
        "## Source content\n\n"
        + fence_source(text)
    )


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunk = text[start:end]
        if end < len(text):
            boundary = max(chunk.rfind("\n\n"), chunk.rfind(". "))
            if boundary >= size // 2:
                end = start + boundary + (0 if chunk[boundary:boundary + 2] == "\n\n" else 1)
                chunk = text[start:end]
        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def chunk_records(record: dict[str, Any], text: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    chunks = chunk_text(text, int(config["chunk_chars"]), int(config["chunk_overlap_chars"]))
    dimensions = int(config["vector_dimensions"])
    try:
        adapter = create_embedding_adapter(config)
    except AdapterError as exc:
        raise BlockedError(f"tool_unavailable: {exc}") from exc
    result = []
    for ordinal, chunk in enumerate(chunks):
        chunk_id = hashlib.sha256(
            f"{record['source_id']}:{record['content_hash']}:{ordinal}:{chunk}".encode("utf-8")
        ).hexdigest()
        try:
            vector = adapter.embed(chunk)
        except AdapterError as exc:
            raise BlockedError(f"tool_unavailable: {exc}") from exc
        result.append(
            {
                "chunk_id": chunk_id,
                "source_id": record["source_id"],
                "source_hash": record["content_hash"],
                "ordinal": ordinal,
                "text": chunk,
                "vector_provider": config["vector_provider"],
                "vector_dimensions": dimensions,
                "vector": vector,
            }
        )
    return result


def active_records_with_updates(known: dict[str, dict[str, Any]], changeset: dict[str, Any]) -> list[dict[str, Any]]:
    records = {path: dict(row) for path, row in known.items()}
    for record in changeset["added"] + changeset["modified"]:
        records[record["relative_path"]] = record
    for rename in changeset["renamed"]:
        records.pop(rename["from_path"], None)
        records[rename["to_path"]] = rename["record"]
    for record in changeset["deleted"]:
        records.pop(record["relative_path"], None)
    return [records[path] for path in sorted(records)]


def render_navigation(records: list[dict[str, Any]], generated_at: str) -> tuple[str, str]:
    lines = ["# LLM-WIKI-RAG Index", "", f"Generated: {generated_at}", "", "## Sources", ""]
    for record in records:
        target = str(record["wiki_page"])
        if target.endswith(".md"):
            target = target[:-3]
        label = Path(record["relative_path"]).name
        lines.append(f"- [[{target}|{label}]]")
    if not records:
        lines.append("- No indexed sources")
    index = "\n".join(lines) + "\n"
    overview = (
        "# LLM-WIKI-RAG Overview\n\n"
        f"Generated: {generated_at}\n\n"
        f"Active sources: {len(records)}\n\n"
        "This Beta overview is deterministic. Reviewed semantic entity synthesis remains a separate worker responsibility.\n"
    )
    return index, overview


def report_path(project: Path, run_id: str) -> Path:
    return project / "agent-workspace" / "runs" / run_id / "run-report.json"


def write_report(project: Path, report: dict[str, Any]) -> Path:
    path = report_path(project, report["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return path


def record_run(conn: sqlite3.Connection, report: dict[str, Any], path: Path) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO runs(run_id,command,mode,started_at,completed_at,status,report_path) VALUES(?,?,?,?,?,?,?)",
        (
            report["run_id"], report["command"], report["mode"], report["started_at"],
            report["completed_at"], report["status"], str(path),
        ),
    )


def cmd_init(project: Path) -> dict[str, Any]:
    started = now_iso()
    run_id = str(uuid.uuid4())
    project.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for directory in (
        "raw/sources", "wiki/sources", "wiki/media", "wiki/queries", "vector_db",
        "agent-workspace/runs", ".llm-wiki-rag",
    ):
        path = project / directory
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(directory + "/")
    templates = {
        "index.md": "# LLM-WIKI-RAG Index\n\n- No indexed sources\n",
        "overview.md": "# LLM-WIKI-RAG Overview\n\nActive sources: 0\n",
        "purpose.md": "# Purpose\n\nDescribe the questions this knowledge base should answer.\n",
        "schema.md": "# Knowledge Schema\n\nRaw sources are immutable. Generated pages require provenance.\n",
        "log.md": "# Operations Log\n",
        ".llm-wiki-rag/config.json": json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    }
    for relative, content in templates.items():
        if write_if_missing(project / relative, content):
            created.append(relative)
    initialize_database(state_path(project))
    report = {
        "schema_version": 1,
        "generator_version": VERSION,
        "run_id": run_id,
        "command": "init",
        "mode": "apply",
        "started_at": started,
        "completed_at": now_iso(),
        "status": "accepted",
        "created": created,
        "warnings": [],
        "errors": [],
    }
    path = write_report(project, report)
    conn = connect(project)
    try:
        record_run(conn, report, path)
        conn.commit()
    finally:
        conn.close()
    report["report_path"] = str(path)
    return report


def report_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: report_safe(item) for key, item in value.items() if key != "absolute_path"}
    if isinstance(value, list):
        return [report_safe(item) for item in value]
    return value


def cmd_update(project: Path, apply: bool, confirm_deletions: bool = False) -> tuple[dict[str, Any], int]:
    started = now_iso()
    run_id = str(uuid.uuid4())
    config = load_config(project)
    conn = connect(project)
    try:
        known = current_sources(conn)
        scanned = scan_sources(project, config)
        changeset = build_changeset(scanned, known, run_id)
        compact_changeset = {key: report_safe(changeset[key]) for key in ("added", "modified", "deleted", "renamed", "unchanged")}
        compact_changeset["run_id"] = run_id
        compact_changeset["requires_approval"] = changeset["requires_approval"]
        report: dict[str, Any] = {
            "schema_version": 1,
            "generator_version": VERSION,
            "run_id": run_id,
            "command": "update",
            "mode": "apply" if apply else "dry_run",
            "started_at": started,
            "completed_at": now_iso(),
            "status": "planned" if not apply else "in_progress",
            "changeset": compact_changeset,
            "planned_writes": [
                r["wiki_page"] for r in changeset["added"] + changeset["modified"]
            ] + [r["wiki_page"] for r in changeset["renamed"]],
            "written_paths": [],
            "chunk_count": 0,
            "warnings": [],
            "errors": [],
            "accepted_by_orchestrator": False,
        }
        if not apply:
            report["completed_at"] = now_iso()
            path = write_report(project, report)
            report["report_path"] = str(path)
            return report, 0
        if changeset["deleted"] and (
            not confirm_deletions or config["deletion_policy"] != "confirm_and_snapshot"
        ):
            report["status"] = "blocked"
            report["errors"].append(
                {
                    "failure_mode": "security_blocked",
                    "message": "Deletion apply requires deletion_policy=confirm_and_snapshot and --confirm-deletions.",
                }
            )
            report["completed_at"] = now_iso()
            path = write_report(project, report)
            record_run(conn, report, path)
            conn.commit()
            report["report_path"] = str(path)
            return report, 2

        changed = changeset["added"] + changeset["modified"] + [item["record"] for item in changeset["renamed"]]
        has_changes = bool(changed or changeset["deleted"])
        if not has_changes:
            report["status"] = "accepted"
            report["accepted_by_orchestrator"] = True
            report["completed_at"] = now_iso()
            path = write_report(project, report)
            record_run(conn, report, path)
            conn.commit()
            report["report_path"] = str(path)
            return report, 0

        prepared: list[tuple[dict[str, Any], str, str, list[dict[str, Any]]]] = []
        generated_at = now_iso()
        extracted, security_findings, approval_path = extract_and_security_gate(project, run_id, changed, config)
        report["security_findings"] = security_findings
        if approval_path:
            report["status"] = "blocked"
            report["errors"].append(
                {"failure_mode": "security_blocked", "message": "Sensitive content requires an approved fingerprint.", "approval_packet": str(approval_path)}
            )
            report["completed_at"] = now_iso()
            path = write_report(project, report)
            record_run(conn, report, path)
            conn.commit()
            report["report_path"] = str(path)
            return report, 2
        report["planned_chunk_count"] = enforce_chunk_budget(extracted, config)
        for record, parser, text in extracted:
            page = render_source_page(record, text, generated_at)
            chunks = chunk_records(record, text, config)
            prepared.append((record, parser, page, chunks))

        active_records = active_records_with_updates(known, changeset)
        index, overview = render_navigation(active_records, generated_at)
        staging = ensure_managed_path(project, project / ".llm-wiki-rag" / "staging" / run_id)
        managed_staging = staging / "managed"
        for record, parser, page, chunks in prepared:
            atomic_write(managed_staging / record["wiki_page"], page)
            report.setdefault("parsers", {})[record["relative_path"]] = parser
            report["chunk_count"] += len(chunks)
        atomic_write(managed_staging / "index.md", index)
        atomic_write(managed_staging / "overview.md", overview)
        atomic_write(staging / "changeset.json", json.dumps(compact_changeset, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        snapshot = create_snapshot(project, conn, "pre-update", run_id)
        report["snapshot_id"] = snapshot["snapshot_id"]
        report["staging_path"] = str(staging)

        rename_ids = {item["source_id"]: item for item in changeset["renamed"]}
        try:
            with conn:
                for record, _parser, _page, chunks in prepared:
                    staged_page = managed_staging / record["wiki_page"]
                    destination = ensure_managed_path(project, project / record["wiki_page"])
                    atomic_write(destination, staged_page.read_text(encoding="utf-8"))
                    report["written_paths"].append(record["wiki_page"])
                    if record["source_id"] in rename_ids:
                        rename = rename_ids[record["source_id"]]
                        previous = known[rename["from_path"]]
                        conn.execute(
                            """
                            UPDATE sources SET relative_path=?,content_hash=?,media_type=?,status='active',last_seen_at=?,wiki_page=?
                            WHERE source_id=?
                            """,
                            (
                                record["relative_path"], record["content_hash"], record["media_type"],
                                generated_at, record["wiki_page"], record["source_id"],
                            ),
                        )
                        first_seen = previous["first_seen_at"]
                    else:
                        previous = known.get(record["relative_path"])
                        first_seen = previous["first_seen_at"] if previous else generated_at
                        conn.execute(
                            """
                            INSERT INTO sources(source_id,relative_path,content_hash,media_type,status,first_seen_at,last_seen_at,wiki_page)
                            VALUES(?,?,?,?,?,?,?,?)
                            ON CONFLICT(relative_path) DO UPDATE SET
                              content_hash=excluded.content_hash,
                              media_type=excluded.media_type,
                              status='active',
                              last_seen_at=excluded.last_seen_at,
                              wiki_page=excluded.wiki_page
                            """,
                            (
                                record["source_id"], record["relative_path"], record["content_hash"], record["media_type"],
                                "active", first_seen, generated_at, record["wiki_page"],
                            ),
                        )
                    conn.execute("DELETE FROM chunks WHERE source_id=?", (record["source_id"],))
                    conn.executemany(
                        """
                        INSERT INTO chunks(chunk_id,source_id,source_hash,ordinal,text,vector_provider,vector_dimensions,vector_json)
                        VALUES(?,?,?,?,?,?,?,?)
                        """,
                        [
                            (
                                chunk["chunk_id"], chunk["source_id"], chunk["source_hash"], chunk["ordinal"],
                                chunk["text"], chunk["vector_provider"], chunk["vector_dimensions"],
                                json.dumps(chunk["vector"], separators=(",", ":")),
                            )
                            for chunk in chunks
                        ],
                    )
                for deleted in changeset["deleted"]:
                    page = ensure_managed_path(project, project / deleted["wiki_page"])
                    if page.exists():
                        page.unlink()
                        report["written_paths"].append(deleted["wiki_page"] + " [deleted]")
                    conn.execute("DELETE FROM chunks WHERE source_id=?", (deleted["source_id"],))
                    conn.execute("DELETE FROM sources WHERE source_id=?", (deleted["source_id"],))
                atomic_write(ensure_managed_path(project, project / "index.md"), index)
                atomic_write(ensure_managed_path(project, project / "overview.md"), overview)
                report["written_paths"].extend(["index.md", "overview.md"])
                report["status"] = "applied"
                report["completed_at"] = now_iso()
                path = write_report(project, report)
                record_run(conn, report, path)
            atomic_write(staging / "status.json", json.dumps({"status": "published", "snapshot_id": snapshot["snapshot_id"]}, indent=2) + "\n")
        except Exception:
            conn.rollback()
            restore_managed_files(project, snapshot_root(project) / snapshot["snapshot_id"])
            atomic_write(staging / "status.json", json.dumps({"status": "rolled_back_files"}, indent=2) + "\n")
            raise

        report["report_path"] = str(path)
        return report, 0
    finally:
        conn.close()


def insert_source_and_chunks(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    chunks: list[dict[str, Any]],
    timestamp: str,
) -> None:
    conn.execute(
        """
        INSERT INTO sources(source_id,relative_path,content_hash,media_type,status,first_seen_at,last_seen_at,wiki_page)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            record["source_id"], record["relative_path"], record["content_hash"], record["media_type"],
            "active", timestamp, timestamp, record["wiki_page"],
        ),
    )
    conn.executemany(
        """
        INSERT INTO chunks(chunk_id,source_id,source_hash,ordinal,text,vector_provider,vector_dimensions,vector_json)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        [
            (
                chunk["chunk_id"], chunk["source_id"], chunk["source_hash"], chunk["ordinal"], chunk["text"],
                chunk["vector_provider"], chunk["vector_dimensions"], json.dumps(chunk["vector"], separators=(",", ":")),
            )
            for chunk in chunks
        ],
    )


def cmd_rebuild(project: Path, apply: bool) -> tuple[dict[str, Any], int]:
    started = now_iso()
    run_id = str(uuid.uuid4())
    config = load_config(project)
    conn = connect(project)
    try:
        scanned = scan_sources(project, config)
        report: dict[str, Any] = {
            "schema_version": 1,
            "generator_version": VERSION,
            "run_id": run_id,
            "command": "rebuild",
            "mode": "apply" if apply else "dry_run",
            "started_at": started,
            "completed_at": now_iso(),
            "status": "planned" if not apply else "in_progress",
            "source_count": len(scanned),
            "planned_writes": [record["wiki_page"] for record in scanned] + ["index.md", "overview.md"],
            "written_paths": [],
            "errors": [],
            "warnings": [],
            "accepted_by_orchestrator": False,
        }
        if not apply:
            path = write_report(project, report)
            report["report_path"] = str(path)
            return report, 0

        generated_at = now_iso()
        staging = ensure_managed_path(project, project / ".llm-wiki-rag" / "staging" / run_id)
        managed = staging / "managed"
        prepared: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        extracted, security_findings, approval_path = extract_and_security_gate(project, run_id, scanned, config)
        report["security_findings"] = security_findings
        if approval_path:
            report["status"] = "blocked"
            report["errors"].append(
                {"failure_mode": "security_blocked", "message": "Sensitive content requires an approved fingerprint.", "approval_packet": str(approval_path)}
            )
            report["completed_at"] = now_iso()
            path = write_report(project, report)
            record_run(conn, report, path)
            conn.commit()
            report["report_path"] = str(path)
            return report, 2
        report["planned_chunk_count"] = enforce_chunk_budget(extracted, config)
        for record, parser_name, text in extracted:
            page = render_source_page(record, text, generated_at)
            chunks = chunk_records(record, text, config)
            prepared.append((record, chunks))
            atomic_write(managed / record["wiki_page"], page)
            report.setdefault("parsers", {})[record["relative_path"]] = parser_name
        index, overview = render_navigation(scanned, generated_at)
        atomic_write(managed / "index.md", index)
        atomic_write(managed / "overview.md", overview)
        snapshot = create_snapshot(project, conn, "pre-rebuild", run_id)
        report["snapshot_id"] = snapshot["snapshot_id"]
        report["staging_path"] = str(staging)
        try:
            with conn:
                destination = ensure_managed_path(project, project / "wiki" / "sources")
                if destination.exists():
                    shutil.rmtree(destination)
                destination.mkdir(parents=True, exist_ok=True)
                staged_sources = managed / "wiki" / "sources"
                if staged_sources.exists():
                    shutil.copytree(staged_sources, destination, dirs_exist_ok=True)
                atomic_write(ensure_managed_path(project, project / "index.md"), index)
                atomic_write(ensure_managed_path(project, project / "overview.md"), overview)
                conn.execute("DELETE FROM chunks")
                conn.execute("DELETE FROM sources")
                for record, chunks in prepared:
                    insert_source_and_chunks(conn, record, chunks, generated_at)
                report["written_paths"] = report["planned_writes"]
                report["status"] = "applied"
                report["completed_at"] = now_iso()
                path = write_report(project, report)
                record_run(conn, report, path)
            atomic_write(staging / "status.json", json.dumps({"status": "published", "snapshot_id": snapshot["snapshot_id"]}, indent=2) + "\n")
        except Exception:
            conn.rollback()
            restore_managed_files(project, snapshot_root(project) / snapshot["snapshot_id"])
            raise
        report["report_path"] = str(path)
        return report, 0
    finally:
        conn.close()


def cmd_delete(project: Path, relative_path: str, apply: bool, confirm: bool) -> tuple[dict[str, Any], int]:
    normalized = Path(relative_path).as_posix().lstrip("/")
    if not normalized.startswith("raw/sources/"):
        normalized = "raw/sources/" + normalized
    conn = connect(project)
    try:
        known = current_sources(conn)
        if normalized not in known:
            raise BlockedError(f"unknown active source: {normalized}")
        if (project / normalized).exists():
            raise BlockedError("delete never removes raw sources; remove or relocate the source first")
        config = load_config(project)
        changeset = build_changeset(scan_sources(project, config), known, str(uuid.uuid4()))
        deleted_paths = {item["relative_path"] for item in changeset["deleted"]}
        if deleted_paths != {normalized}:
            raise BlockedError(f"delete scope mismatch; pending deletions are: {sorted(deleted_paths)}")
    finally:
        conn.close()
    if not apply or not confirm:
        report, _ = cmd_update(project, apply=False)
        report["command"] = "delete"
        report["status"] = "planned"
        report["required_confirmation"] = "--apply --confirm"
        atomic_write(Path(report["report_path"]), json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return report, 0
    return cmd_update(project, apply=True, confirm_deletions=True)


def snapshot_inventory(project: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    root = snapshot_root(project)
    if root.exists():
        for manifest_path in sorted(root.glob("*/manifest.json"), reverse=True):
            try:
                items.append(json.loads(manifest_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                items.append({"snapshot_id": manifest_path.parent.name, "status": "schema_mismatch"})
    return items


def cmd_snapshots(project: Path) -> tuple[dict[str, Any], int]:
    items = snapshot_inventory(project)
    return {"command": "snapshots", "status": "accepted", "count": len(items), "snapshots": items}, 0


def cmd_conflicts(project: Path) -> tuple[dict[str, Any], int]:
    conn = connect(project)
    try:
        rows = conn.execute(
            "SELECT conflict_id,entity_key,source_ids_json,details_json,status,created_at,resolved_at FROM conflicts ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    conflicts = []
    for row in rows:
        item = dict(row)
        item["source_ids"] = json.loads(item.pop("source_ids_json"))
        item["details"] = json.loads(item.pop("details_json"))
        conflicts.append(item)
    return {"command": "conflicts", "status": "accepted", "count": len(conflicts), "conflicts": conflicts}, 0


def cmd_migrate(project: Path, apply: bool) -> tuple[dict[str, Any], int]:
    database = state_path(project)
    if not database.exists():
        raise BlockedError("project is not initialized")
    plan = migration_plan(database)
    if not apply:
        return {"command": "migrate", "mode": "dry_run", "status": "planned", **plan}, 0
    try:
        result = apply_migrations(project)
    except RuntimeError as exc:
        raise BlockedError(f"schema_mismatch: {exc}") from exc
    return {"command": "migrate", "mode": "apply", "status": "accepted", **result}, 0


def cmd_approve(project: Path, fingerprint: str, scope: str, confirm: bool) -> tuple[dict[str, Any], int]:
    if not re.fullmatch(r"[a-f0-9]{16}", fingerprint):
        raise BlockedError("approval fingerprint must be 16 lowercase hex characters")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", scope):
        raise BlockedError("invalid approval scope")
    if not confirm:
        return {
            "command": "approve",
            "mode": "dry_run",
            "status": "blocked",
            "fingerprint": fingerprint,
            "scope": scope,
            "required_confirmation": "--confirm",
        }, 2
    config = load_config(project)
    security = dict(config.get("security") or {})
    approved = sorted(set(str(value) for value in security.get("approved_fingerprints", [])) | {fingerprint})
    security["approved_fingerprints"] = approved
    config["security"] = security
    atomic_write(config_path(project), json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    approval_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    report = {
        "command": "approve",
        "mode": "apply",
        "status": "accepted",
        "approval_id": approval_id,
        "run_id": run_id,
        "fingerprint": fingerprint,
        "scope": scope,
        "secret_value_recorded": False,
        "decided_at": now_iso(),
    }
    path = write_report(project, report)
    conn = connect(project)
    try:
        conn.execute(
            "INSERT INTO approvals(approval_id,run_id,scope,decision,decided_at,evidence_path) VALUES(?,?,?,?,?,?)",
            (approval_id, run_id, f"{scope}:{fingerprint}", "approved", report["decided_at"], str(path)),
        )
        record_run(conn, {**report, "started_at": report["decided_at"], "completed_at": report["decided_at"]}, path)
        conn.commit()
    finally:
        conn.close()
    report["report_path"] = str(path)
    return report, 0


def cmd_rollback(project: Path, snapshot_id: str, confirm: bool) -> tuple[dict[str, Any], int]:
    started = now_iso()
    run_id = str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9_.:+-]+", snapshot_id):
        raise BlockedError("invalid snapshot id")
    target = (snapshot_root(project) / snapshot_id).resolve()
    root = snapshot_root(project).resolve()
    if root not in target.parents or not (target / "manifest.json").exists():
        raise BlockedError("snapshot not found")
    if not confirm:
        return {
            "run_id": run_id,
            "command": "rollback",
            "mode": "dry_run",
            "status": "blocked",
            "snapshot_id": snapshot_id,
            "required_confirmation": "--confirm",
        }, 2
    snapshot_db = sqlite3.connect(target / "state.db")
    snapshot_db.row_factory = sqlite3.Row
    try:
        expected_sources = snapshot_db.execute("SELECT relative_path,content_hash FROM sources WHERE status='active'").fetchall()
    finally:
        snapshot_db.close()
    mismatches = []
    for row in expected_sources:
        source = project / row["relative_path"]
        if not source.exists() or file_hash(source) != row["content_hash"]:
            mismatches.append(row["relative_path"])
    if mismatches:
        raise BlockedError(f"rollback source-state mismatch: {mismatches}")
    conn = connect(project)
    try:
        pre = create_snapshot(project, conn, "pre-rollback", run_id)
        conn.commit()
    finally:
        conn.close()
    restore_managed_files(project, target)
    restore_database(project, target)
    report = {
        "schema_version": 1,
        "generator_version": VERSION,
        "run_id": run_id,
        "command": "rollback",
        "mode": "apply",
        "started_at": started,
        "completed_at": now_iso(),
        "status": "restored",
        "snapshot_id": snapshot_id,
        "pre_rollback_snapshot_id": pre["snapshot_id"],
        "errors": [],
        "warnings": [],
    }
    path = write_report(project, report)
    restored = connect(project)
    try:
        record_run(restored, report, path)
        restored.commit()
    finally:
        restored.close()
    report["report_path"] = str(path)
    return report, 0


def cmd_query(project: Path, text: str, limit: int) -> tuple[dict[str, Any], int]:
    if not text.strip():
        raise BlockedError("query text is empty")
    config = load_config(project)
    try:
        adapter = create_embedding_adapter(config)
        query_vector = adapter.embed(text)
    except AdapterError as exc:
        raise BlockedError(f"tool_unavailable: {exc}") from exc
    conn = connect(project)
    try:
        rows = conn.execute(
            """
            SELECT c.chunk_id,c.source_id,c.ordinal,c.text,c.vector_provider,c.vector_dimensions,c.vector_json,s.relative_path
            FROM chunks c JOIN sources s ON s.source_id=c.source_id WHERE s.status='active'
            """
        ).fetchall()
    finally:
        conn.close()
    results = []
    for row in rows:
        if row["vector_provider"] != config["vector_provider"] or row["vector_dimensions"] != len(query_vector):
            continue
        vector = json.loads(row["vector_json"])
        score = sum(float(a) * float(b) for a, b in zip(query_vector, vector))
        results.append(
            {
                "score": round(score, 8),
                "source_id": row["source_id"],
                "relative_path": row["relative_path"],
                "chunk_id": row["chunk_id"],
                "ordinal": row["ordinal"],
                "text_preview": row["text"][:300],
            }
        )
    results.sort(key=lambda item: (-item["score"], item["relative_path"], item["ordinal"]))
    return {
        "command": "query",
        "status": "accepted",
        "provider": config["vector_provider"],
        "query": text,
        "results": results[: max(1, min(limit, 50))],
    }, 0


def strip_fenced_blocks(text: str) -> str:
    return re.sub(r"(?ms)^(`{3,}|~{3,}).*?^\1\s*$", "", text)


def resolve_wikilink(project: Path, source_file: Path, target: str) -> bool:
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    if not target or re.match(r"^[a-z]+://", target, flags=re.I):
        return True
    path_target = Path(target)
    candidates: list[Path] = []
    if "/" in target or "\\" in target:
        candidates.extend([project / path_target, source_file.parent / path_target])
    else:
        candidates.extend([source_file.parent / path_target, project / path_target, project / "wiki" / path_target])
        candidates.extend((project / "wiki").rglob(path_target.name + ".md"))
    for candidate in candidates:
        if candidate.suffix.lower() != ".md":
            candidate = candidate.with_suffix(".md")
        if candidate.exists():
            return True
    return False


def audit_project(project: Path, write: bool = True) -> tuple[dict[str, Any], int]:
    started = now_iso()
    run_id = str(uuid.uuid4())
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    required = ["raw/sources", "wiki/sources", ".llm-wiki-rag/state.db", "index.md", "overview.md", "purpose.md", "schema.md"]
    for relative in required:
        if not (project / relative).exists():
            errors.append({"code": "missing_required_path", "path": relative})
    conn = connect(project)
    try:
        sources = [dict(row) for row in conn.execute("SELECT * FROM sources WHERE status='active'")]
        source_ids = {row["source_id"] for row in sources}
        for row in sources:
            source = project / row["relative_path"]
            page = project / row["wiki_page"]
            if not source.exists():
                errors.append({"code": "missing_active_source", "path": row["relative_path"]})
            elif file_hash(source) != row["content_hash"]:
                errors.append({"code": "source_hash_mismatch", "path": row["relative_path"]})
            if not page.exists():
                errors.append({"code": "missing_wiki_page", "path": row["wiki_page"]})
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks WHERE source_id=?", (row["source_id"],)).fetchone()[0]
            if chunk_count == 0:
                errors.append({"code": "source_without_chunks", "path": row["relative_path"]})
        orphan_rows = conn.execute("SELECT DISTINCT source_id FROM chunks").fetchall()
        for row in orphan_rows:
            if row["source_id"] not in source_ids:
                errors.append({"code": "orphan_chunks", "source_id": row["source_id"]})
        for md_file in sorted([project / "index.md", project / "overview.md"] + list((project / "wiki").rglob("*.md"))):
            if not md_file.exists():
                continue
            text = strip_fenced_blocks(md_file.read_text(encoding="utf-8"))
            for match in re.finditer(r"\[\[([^\]]+)\]\]", text):
                if not resolve_wikilink(project, md_file, match.group(1)):
                    errors.append(
                        {"code": "broken_wikilink", "path": md_file.relative_to(project).as_posix(), "target": match.group(1)}
                    )
        provider_rows = conn.execute("SELECT DISTINCT vector_provider,vector_dimensions FROM chunks").fetchall()
        if len(provider_rows) > 1:
            errors.append({"code": "vector_provider_drift", "detail": str([tuple(row) for row in provider_rows])})
        elif provider_rows:
            config = load_config(project)
            provider, dimensions = tuple(provider_rows[0])
            if provider != config["vector_provider"] or dimensions != int(config["vector_dimensions"]):
                errors.append({"code": "vector_config_mismatch", "detail": f"stored={provider}/{dimensions}"})
        open_conflicts = conn.execute("SELECT COUNT(*) FROM conflicts WHERE status='open'").fetchone()[0]
        if open_conflicts:
            warnings.append({"code": "open_conflicts", "count": str(open_conflicts)})
        report = {
            "schema_version": 1,
            "generator_version": VERSION,
            "run_id": run_id,
            "command": "audit",
            "mode": "read_only",
            "started_at": started,
            "completed_at": now_iso(),
            "status": "accepted" if not errors else "rejected",
            "passed": not errors,
            "counts": {
                "sources": len(sources),
                "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "open_conflicts": open_conflicts,
                "errors": len(errors),
                "warnings": len(warnings),
            },
            "errors": errors,
            "warnings": warnings,
        }
        if write:
            path = write_report(project, report)
            record_run(conn, report, path)
            conn.commit()
            report["report_path"] = str(path)
        return report, 0 if not errors else 3
    finally:
        conn.close()


def cmd_status(project: Path) -> tuple[dict[str, Any], int]:
    started = now_iso()
    run_id = str(uuid.uuid4())
    config = load_config(project)
    conn = connect(project)
    try:
        known = current_sources(conn)
        changeset = build_changeset(scan_sources(project, config), known, run_id)
        last = conn.execute("SELECT * FROM runs ORDER BY completed_at DESC LIMIT 1").fetchone()
        report = {
            "schema_version": 1,
            "generator_version": VERSION,
            "run_id": run_id,
            "command": "status",
            "mode": "read_only",
            "started_at": started,
            "completed_at": now_iso(),
            "status": "accepted",
            "counts": {
                "known_sources": len(known),
                "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "added": len(changeset["added"]),
                "modified": len(changeset["modified"]),
                "deleted": len(changeset["deleted"]),
                "renamed": len(changeset["renamed"]),
                "unchanged": len(changeset["unchanged"]),
                "snapshots": len(snapshot_inventory(project)),
                "open_conflicts": conn.execute("SELECT COUNT(*) FROM conflicts WHERE status='open'").fetchone()[0],
            },
            "last_run": dict(last) if last else None,
            "warnings": [],
            "errors": [],
        }
        path = write_report(project, report)
        record_run(conn, report, path)
        conn.commit()
        report["report_path"] = str(path)
        return report, 0
    finally:
        conn.close()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="LLM-WIKI-RAG Production 1.0.1")
    sub = value.add_subparsers(dest="command", required=True)
    for name in ("init", "update", "status", "audit", "rebuild", "snapshots", "conflicts", "migrate"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True, help="Absolute path to a specific knowledge project")
        if name == "update":
            command.add_argument("--apply", action="store_true", help="Publish the staged update")
            command.add_argument("--confirm-deletions", action="store_true", help="Allow snapshotted cleanup for detected deletions")
        if name == "rebuild":
            command.add_argument("--apply", action="store_true", help="Snapshot and rebuild all derived state")
        if name == "migrate":
            command.add_argument("--apply", action="store_true", help="Back up and apply pending schema migrations")
    delete = sub.add_parser("delete")
    delete.add_argument("--project", required=True)
    delete.add_argument("--source", required=True, help="Missing raw source path to clean from derived state")
    delete.add_argument("--apply", action="store_true")
    delete.add_argument("--confirm", action="store_true")
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--project", required=True)
    rollback.add_argument("--snapshot", required=True)
    rollback.add_argument("--confirm", action="store_true")
    query = sub.add_parser("query")
    query.add_argument("--project", required=True)
    query.add_argument("--text", required=True)
    query.add_argument("--limit", type=int, default=5)
    approve = sub.add_parser("approve")
    approve.add_argument("--project", required=True)
    approve.add_argument("--fingerprint", required=True)
    approve.add_argument("--scope", required=True)
    approve.add_argument("--confirm", action="store_true")
    return value


def finalize_with_audit(project: Path, report: dict[str, Any], code: int) -> tuple[dict[str, Any], int]:
    if code != 0 or report.get("mode") != "apply":
        return report, code
    audit, audit_code = audit_project(project)
    report["post_audit"] = {"passed": audit["passed"], "report_path": audit.get("report_path")}
    if audit_code:
        report["status"] = "rejected"
        report.setdefault("errors", []).append({"failure_mode": "regression_detected", "message": "post-apply audit failed"})
        code = audit_code
    else:
        report["status"] = "accepted"
        report["accepted_by_orchestrator"] = True
    if report.get("report_path"):
        atomic_write(Path(report["report_path"]), json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if report.get("run_id"):
        run_conn = connect(project)
        try:
            run_conn.execute(
                "UPDATE runs SET command=?,status=?,completed_at=? WHERE run_id=?",
                (report.get("command", "unknown"), report["status"], now_iso(), report["run_id"]),
            )
            run_conn.commit()
        finally:
            run_conn.close()
    return report, code


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project: Path | None = None
    operation_started = time.monotonic()
    try:
        project = validate_project(args.project)
        mutating = (
            args.command == "init"
            or (args.command in {"update", "rebuild", "migrate"} and bool(getattr(args, "apply", False)))
            or (args.command == "delete" and bool(args.apply and args.confirm))
            or (args.command == "rollback" and bool(args.confirm))
            or (args.command == "approve" and bool(args.confirm))
        )
        stale_after = 3600
        if config_path(project).exists():
            stale_after = int((load_config(project).get("operations") or {}).get("lock_stale_after_seconds", 3600))
        lock = ProjectLock(project, args.command, stale_after) if mutating else nullcontext()
        with lock:
            if args.command == "init":
                report = cmd_init(project)
                code = 0
            elif args.command == "update":
                report, code = cmd_update(project, args.apply, args.confirm_deletions)
                report, code = finalize_with_audit(project, report, code)
            elif args.command == "rebuild":
                report, code = cmd_rebuild(project, args.apply)
                report, code = finalize_with_audit(project, report, code)
            elif args.command == "delete":
                report, code = cmd_delete(project, args.source, args.apply, args.confirm)
                if args.apply and args.confirm:
                    report["command"] = "delete"
                    report, code = finalize_with_audit(project, report, code)
            elif args.command == "rollback":
                report, code = cmd_rollback(project, args.snapshot, args.confirm)
                report, code = finalize_with_audit(project, report, code)
            elif args.command == "snapshots":
                report, code = cmd_snapshots(project)
            elif args.command == "conflicts":
                report, code = cmd_conflicts(project)
            elif args.command == "migrate":
                report, code = cmd_migrate(project, args.apply)
            elif args.command == "query":
                report, code = cmd_query(project, args.text, args.limit)
            elif args.command == "approve":
                report, code = cmd_approve(project, args.fingerprint, args.scope, args.confirm)
            elif args.command == "audit":
                report, code = audit_project(project)
            else:
                report, code = cmd_status(project)
        duration = round(time.monotonic() - operation_started, 4)
        emit_event(project, {"event": "command_completed", "command": args.command, "status": report.get("status"), "exit_code": code, "duration_seconds": duration})
        update_metrics(project, args.command, str(report.get("status", "unknown")), duration)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return code
    except (BlockedError, OperationalBlocked) as exc:
        if project is not None:
            duration = round(time.monotonic() - operation_started, 4)
            emit_event(project, {"event": "command_blocked", "command": args.command, "failure_mode": "security_blocked", "duration_seconds": duration})
            update_metrics(project, args.command, "blocked", duration)
        print(json.dumps({"status": "blocked", "failure_mode": "security_blocked", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    except (json.JSONDecodeError, sqlite3.DatabaseError) as exc:
        if project is not None:
            duration = round(time.monotonic() - operation_started, 4)
            emit_event(project, {"event": "command_failed", "command": args.command, "failure_mode": "schema_mismatch", "duration_seconds": duration})
            update_metrics(project, args.command, "failed", duration)
        print(json.dumps({"status": "failed", "failure_mode": "schema_mismatch", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 3
    except Exception as exc:  # final boundary: never expose a traceback by default
        if project is not None:
            duration = round(time.monotonic() - operation_started, 4)
            emit_event(project, {"event": "command_failed", "command": args.command, "failure_mode": "partial_output", "duration_seconds": duration})
            update_metrics(project, args.command, "failed", duration)
        print(json.dumps({"status": "failed", "failure_mode": "partial_output", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
