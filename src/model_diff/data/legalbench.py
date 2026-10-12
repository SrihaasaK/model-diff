"""LegalBench adapter: one Hugging Face config per task, pinned to a dataset commit."""

from __future__ import annotations

from pathlib import Path

from datasets import load_dataset

from ..config import Config
from .cases import Case, CorpusAdapter, JsonlAdapter, check_unique_ids
from .tasks import TaskSpec


def compose_input(row: dict, fields: list[tuple[str, str]]) -> str:
    """Join the task's input columns, each under its heading (an empty heading adds none)."""
    parts = []
    for column, heading in fields:
        text = str(row[column]).strip()
        parts.append(f"{heading}:\n{text}" if heading else text)
    return "\n\n".join(parts)


class LegalBenchAdapter:
    def __init__(self, dataset: str, revision: str, split: str, tasks: dict[str, TaskSpec]):
        self.dataset = dataset
        self.revision = revision
        self.split = split
        self.tasks = tasks

    def load_rows(self, task: str) -> list[dict]:
        ds = load_dataset(self.dataset, task, revision=self.revision, split=self.split)
        return [dict(row) for row in ds]

    def to_case(self, task: str, row: dict) -> Case:
        spec = self.tasks[task]
        gold = spec.label_map.get(row["answer"], row["answer"])
        if gold not in spec.labels:
            raise ValueError(f"{task}: gold label {row['answer']!r} maps to {gold!r}, not in {spec.labels}")
        return Case(
            case_id=f"{task}-{int(row['index']):05d}",
            task=task,
            input=compose_input(row, spec.input_fields),
            gold_label=gold,
            license=spec.license,
        )

    def load_pool(self) -> list[Case]:
        cases = [self.to_case(task, row) for task in sorted(self.tasks) for row in self.load_rows(task)]
        check_unique_ids(cases)
        return cases


def build_adapter(cfg: Config, tasks: dict[str, TaskSpec]) -> CorpusAdapter:
    if cfg.corpus.adapter == "jsonl":
        return JsonlAdapter(Path(cfg.corpus.path))
    if not cfg.corpus.revision:
        raise SystemExit("corpus.revision must pin a dataset commit for reproducible sampling.")
    return LegalBenchAdapter(cfg.corpus.dataset, cfg.corpus.revision, cfg.corpus.split, tasks)
