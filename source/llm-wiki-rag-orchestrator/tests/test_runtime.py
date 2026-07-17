from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from production_runtime import OperationalBlocked, ProjectLock, scan_sensitive_text  # noqa: E402
from vector_adapters import AdapterError, HashingEmbeddingAdapter, create_embedding_adapter  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def test_hashing_adapter_is_deterministic(self) -> None:
        adapter = HashingEmbeddingAdapter(dimensions=32)
        self.assertEqual(adapter.embed("alpha beta"), adapter.embed("alpha beta"))
        self.assertEqual(len(adapter.embed("alpha")), 32)

    def test_http_adapter_rejects_insecure_endpoint(self) -> None:
        with self.assertRaises(AdapterError):
            create_embedding_adapter(
                {
                    "vector_provider": "http-json-v1",
                    "vector_dimensions": 3,
                    "http_embedding": {"endpoint": "http://example.invalid", "model": "x", "token_env": "MISSING"},
                }
            )

    def test_secret_scanner_redacts_values(self) -> None:
        value = "api_key=ABCDEF1234567890SECRET"
        findings = scan_sensitive_text(value)
        self.assertTrue(findings)
        self.assertTrue(all(value not in json.dumps(item.as_dict()) for item in findings))

    def test_project_lock_blocks_live_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            lock = project / ".llm-wiki-rag" / "operation.lock"
            lock.parent.mkdir(parents=True)
            lock.write_text(json.dumps({"pid": os.getpid(), "created_epoch": time.time()}), encoding="utf-8")
            with self.assertRaises(OperationalBlocked):
                with ProjectLock(project, "test"):
                    pass

    def test_project_lock_recovers_dead_stale_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            lock = project / ".llm-wiki-rag" / "operation.lock"
            lock.parent.mkdir(parents=True)
            lock.write_text(json.dumps({"pid": 99999999, "created_epoch": 1}), encoding="utf-8")
            with ProjectLock(project, "test", stale_after_seconds=1):
                self.assertTrue(lock.exists())
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
