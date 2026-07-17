#!/usr/bin/env python3
"""Versioned embedding adapters for LLM-WIKI-RAG.

The default hashing adapter is deterministic and local. The HTTP adapter is
opt-in, never logs credentials, and requires an HTTPS endpoint plus an
environment-variable name containing the bearer token.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse


class AdapterError(RuntimeError):
    pass


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class EmbeddingAdapter(Protocol):
    name: str

    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class HashingEmbeddingAdapter:
    dimensions: int = 128
    name: str = "hashing-v1"

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        for token in re.findall(r"[\w'-]+", text.lower(), flags=re.UNICODE):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            values[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in values))
        return [round(value / norm, 8) for value in values] if norm else values


@dataclass(frozen=True)
class HttpJsonEmbeddingAdapter:
    endpoint: str
    model: str
    token_env: str
    dimensions: int
    timeout_seconds: int = 30
    name: str = "http-json-v1"

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise AdapterError("http-json-v1 requires an absolute HTTPS endpoint")
        if not self.model.strip():
            raise AdapterError("http-json-v1 requires a model identifier")
        if not self.token_env or self.token_env not in os.environ:
            raise AdapterError(f"required token environment variable is missing: {self.token_env}")

    def embed(self, text: str) -> list[float]:
        token = os.environ.get(self.token_env)
        if not token:
            raise AdapterError(f"required token environment variable is empty: {self.token_env}")
        payload = json.dumps({"model": self.model, "input": [text]}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(NoRedirectHandler())
            with opener.open(request, timeout=self.timeout_seconds) as response:
                data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AdapterError(f"embedding endpoint request failed: {type(exc).__name__}") from exc
        try:
            vector = [float(value) for value in data["data"][0]["embedding"]]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise AdapterError("embedding endpoint returned an incompatible response schema") from exc
        if len(vector) != self.dimensions:
            raise AdapterError(f"embedding dimensions mismatch: expected {self.dimensions}, received {len(vector)}")
        return vector


def create_embedding_adapter(config: dict[str, Any]) -> EmbeddingAdapter:
    provider = str(config.get("vector_provider", "hashing-v1"))
    dimensions = int(config.get("vector_dimensions", 128))
    if provider == "hashing-v1":
        return HashingEmbeddingAdapter(dimensions=dimensions)
    if provider == "http-json-v1":
        http = config.get("http_embedding") or {}
        return HttpJsonEmbeddingAdapter(
            endpoint=str(http.get("endpoint", "")),
            model=str(http.get("model", "")),
            token_env=str(http.get("token_env", "")),
            dimensions=dimensions,
            timeout_seconds=int(http.get("timeout_seconds", 30)),
        )
    raise AdapterError(f"unsupported vector_provider: {provider}")
