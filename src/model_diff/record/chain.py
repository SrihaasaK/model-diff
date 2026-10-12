"""Re-walk a run's hash chain and report tampering or truncation. Needs no network."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from ..hashing import sha256_file, sha256_text
from .recorder import CALLS, HEAD, MANIFEST, RUN_CONFIG, read_lines
from .schema import CallRecord


@dataclass
class VerifyResult:
    records: int = 0
    head: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def verify_run(run_dir: Path) -> VerifyResult:
    result = VerifyResult()
    config_path = run_dir / RUN_CONFIG
    if not config_path.exists():
        result.problems.append(f"{RUN_CONFIG} is missing; the chain has no anchor")
        return result
    config = json.loads(config_path.read_text(encoding="utf-8"))
    pinned = set(config.get("pinned_models", []))

    for name, expected in sorted(config.get("artifacts", {}).items()):
        path = run_dir / name
        if not path.exists():
            result.problems.append(f"frozen artifact {name} is missing")
        elif sha256_file(path) != expected:
            result.problems.append(f"frozen artifact {name} does not match the hash in {RUN_CONFIG}")

    calls = read_lines(run_dir / CALLS)
    manifest = read_lines(run_dir / MANIFEST)
    if len(calls) != len(manifest):
        result.problems.append(f"{CALLS} has {len(calls)} lines but {MANIFEST} has {len(manifest)}")

    prev = sha256_file(config_path)
    for seq, (call_line, entry_line) in enumerate(zip(calls, manifest)):
        try:
            entry = json.loads(entry_line)
        except json.JSONDecodeError:
            result.problems.append(f"manifest line {seq} is not valid JSON")
            break
        if entry.get("seq") != seq:
            result.problems.append(f"manifest line {seq} has seq {entry.get('seq')}: lines were removed or reordered")
        if entry.get("prev_sha256") != prev:
            result.problems.append(f"manifest line {seq} does not chain to the line before it")
        if entry.get("record_sha256") != sha256_text(call_line):
            result.problems.append(f"record {seq} in {CALLS} was altered (hash mismatch)")
        try:
            record = CallRecord.model_validate_json(call_line)
        except ValidationError:
            result.problems.append(f"record {seq} is not a valid call record")
        else:
            if record.run_id != config.get("run_id"):
                result.problems.append(f"record {seq} belongs to run {record.run_id!r}")
            if record.model_id not in pinned:
                result.problems.append(f"record {seq} uses unpinned model {record.model_id!r}")
        prev = sha256_text(entry_line)
    result.records = min(len(calls), len(manifest))
    result.head = prev

    head_path = run_dir / HEAD
    if not head_path.exists():
        if manifest:
            result.problems.append(f"{HEAD} is missing, so truncation of both files cannot be ruled out")
    else:
        head = json.loads(head_path.read_text(encoding="utf-8"))
        if head.get("count") != len(manifest):
            result.problems.append(
                f"{HEAD} records {head.get('count')} lines but {MANIFEST} has {len(manifest)}: "
                "the log was truncated or extended outside the recorder"
            )
        elif manifest and head.get("last_manifest_line_sha256") != sha256_text(manifest[-1]):
            result.problems.append(f"the last manifest line does not match {HEAD}")
    return result
