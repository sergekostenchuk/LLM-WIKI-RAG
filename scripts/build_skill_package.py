#!/usr/bin/env python3
"""Build the portable .skill archive without external tooling."""

from __future__ import annotations

import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "llm-wiki-rag-orchestrator"
OUTPUT = ROOT / "dist" / "llm-wiki-rag-orchestrator.skill"
EXCLUDED_NAMES = {".DS_Store", "__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def included(path: Path) -> bool:
    relative = path.relative_to(SOURCE)
    return not any(part in EXCLUDED_NAMES for part in relative.parts) and path.suffix not in EXCLUDED_SUFFIXES


def main() -> int:
    if not (SOURCE / "SKILL.md").exists():
        raise SystemExit(f"Skill source not found: {SOURCE}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in SOURCE.rglob("*") if path.is_file() and included(path))
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in files:
            relative = source.relative_to(SOURCE.parent)
            archive.write(source, relative.as_posix())
    print(f"Built {OUTPUT} with {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
