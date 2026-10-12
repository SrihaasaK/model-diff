"""Canonical JSON and SHA-256 helpers shared by the recorder, prompts, and sampler."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    """One stable serialization: sorted keys, no whitespace, UTF-8 text kept as-is."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())
