"""Append-only call log with a hash-chained manifest.

A run directory holds:

  run_config.json  frozen run settings: run_id, pinned model IDs, and the
                   SHA-256 of each frozen artifact (cases, prompts, models snapshot)
  calls.jsonl      one canonical-JSON CallRecord per line
  manifest.jsonl   one line per record: {"seq", "record_sha256", "prev_sha256"}.
                   record_sha256 hashes the record's line in calls.jsonl;
                   prev_sha256 hashes the previous manifest line, and for the
                   first line it hashes run_config.json, which ties the chain
                   to the frozen settings and artifacts.
  HEAD.json        {"count", "last_manifest_line_sha256"} after each append, so
                   truncating both files is detectable.

The chain makes partial edits, deletions, and reordering detectable. Someone
able to rewrite every file could rebuild a consistent chain, so publish the
head hash (the report prints it) to anchor a run externally.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

from ..hashing import canonical_json, sha256_file, sha256_text
from .schema import CallRecord

CALLS = "calls.jsonl"
MANIFEST = "manifest.jsonl"
HEAD = "HEAD.json"
RUN_CONFIG = "run_config.json"


class ModelPinError(RuntimeError):
    """A record names a model outside the run's pinned set, or the API answered with another model."""


def write_head(run_dir: Path, count: int, last_line_sha: str | None) -> None:
    tmp = run_dir / (HEAD + ".tmp")
    tmp.write_text(json.dumps({"count": count, "last_manifest_line_sha256": last_line_sha}) + "\n", encoding="utf-8")
    os.replace(tmp, run_dir / HEAD)


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def repair_interrupted_append(run_dir: Path) -> int:
    """Undo an append that a crash cut short; returns how many records were set aside.

    An append writes calls.jsonl, then manifest.jsonl, then HEAD.json, so a line
    beyond HEAD's count was never confirmed. Exactly one such line in either
    file is the signature of an interrupted append: it is moved to
    orphans.jsonl, outside the chain, and its request is simply re-sent later.
    Any other mismatch is left alone for `verify` to report.
    """
    head_path = run_dir / HEAD
    count = json.loads(head_path.read_text(encoding="utf-8"))["count"] if head_path.exists() else 0
    calls, manifest = read_lines(run_dir / CALLS), read_lines(run_dir / MANIFEST)
    extra_calls, extra_manifest = len(calls) - count, len(manifest) - count
    if extra_calls not in (0, 1) or extra_manifest not in (0, 1) or not (extra_calls or extra_manifest):
        return 0
    orphan = {"moved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "calls_line": calls[count] if extra_calls else None,
              "manifest_line": manifest[count] if extra_manifest else None}
    with open(run_dir / "orphans.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(orphan) + "\n")
    for name, lines in ((CALLS, calls), (MANIFEST, manifest)):
        (run_dir / name).write_text("".join(line + "\n" for line in lines[:count]), encoding="utf-8")
    return 1


class Recorder:
    def __init__(self, run_dir: Path):
        repair_interrupted_append(run_dir)
        self.run_dir = run_dir
        config = json.loads((run_dir / RUN_CONFIG).read_text(encoding="utf-8"))
        self.run_id: str = config["run_id"]
        self.pinned: set[str] = set(config["pinned_models"])
        self.genesis = sha256_file(run_dir / RUN_CONFIG)

        calls = read_lines(run_dir / CALLS)
        manifest = read_lines(run_dir / MANIFEST)
        if len(calls) != len(manifest):
            raise RuntimeError(
                f"{CALLS} has {len(calls)} lines but {MANIFEST} has {len(manifest)}; "
                f"run `model-diff verify {self.run_id}` before continuing."
            )
        self.count = len(manifest)
        self.prev = sha256_text(manifest[-1]) if manifest else self.genesis
        self.records = [CallRecord.model_validate_json(line) for line in calls]

    @contextmanager
    def _locked(self):
        with open(self.run_dir / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def append(self, record: CallRecord) -> None:
        if record.run_id != self.run_id:
            raise ValueError(f"record run_id {record.run_id!r} does not match run {self.run_id!r}")
        if record.model_id not in self.pinned:
            raise ModelPinError(f"model {record.model_id!r} is not pinned for run {self.run_id}")
        if record.response_model is not None and record.response_model != record.model_id:
            raise ModelPinError(f"requested {record.model_id!r} but the API answered as {record.response_model!r}")

        line = canonical_json(record.model_dump())
        entry = canonical_json({"seq": self.count, "record_sha256": sha256_text(line), "prev_sha256": self.prev})
        with self._locked():
            for name, text in ((CALLS, line), (MANIFEST, entry)):
                with open(self.run_dir / name, "a", encoding="utf-8") as fh:
                    fh.write(text + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
            self.count += 1
            self.prev = sha256_text(entry)
            write_head(self.run_dir, self.count, self.prev)
        self.records.append(record)

    @property
    def head(self) -> str:
        """SHA-256 of the last manifest line (the run_config hash before any record)."""
        return self.prev
