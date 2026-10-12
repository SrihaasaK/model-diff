"""The case record and the corpus adapter interface.

A corpus adapter turns some source into a pool of Cases. Every adapter yields
the same five fields, so prompting, recording, scoring, and diffing never
depend on where cases came from. A private suite needs no code: write a JSONL
file with these fields and set corpus.adapter to "jsonl" in config.yaml.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ..hashing import canonical_json


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    task: str
    input: str
    gold_label: str
    license: str


class CorpusAdapter(Protocol):
    def load_pool(self) -> list[Case]:
        """Every available case, before sampling."""
        ...


class JsonlAdapter:
    """A corpus supplied as JSONL with the Case fields, one case per line."""

    def __init__(self, path: Path):
        self.path = path

    def load_pool(self) -> list[Case]:
        if not self.path.exists():
            raise SystemExit(f"Corpus file not found: {self.path}")
        cases = [Case.model_validate_json(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        check_unique_ids(cases)
        return cases


def check_unique_ids(cases: list[Case]) -> None:
    dupes = [cid for cid, n in Counter(c.case_id for c in cases).items() if n > 1]
    if dupes:
        raise ValueError(f"duplicate case_id values, e.g. {dupes[:3]}")


def write_cases(path: Path, cases: list[Case]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(canonical_json(case.model_dump()) + "\n")


def read_cases(path: Path) -> list[Case]:
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `model-diff sample` first.")
    return [Case.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def task_labels(cases: list[Case], declared: dict[str, list[str]]) -> dict[str, list[str]]:
    """Each task's label set: declared in tasks.yaml, else the distinct gold labels."""
    labels = {}
    for task in sorted({c.task for c in cases}):
        labels[task] = declared.get(task) or sorted({c.gold_label for c in cases if c.task == task})
    return labels


def dump_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
