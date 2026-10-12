"""Build the exact requests sent to each arm.

Every arm receives byte-identical prompt text for a case; arms differ only in
the parameters configured for them. prompt_sha256 covers the system prompt
and messages, so equal hashes across arms prove the prompts matched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .data.cases import Case
from .data.tasks import TaskSpec
from .hashing import canonical_json, sha256_file, sha256_text

PLACEHOLDER = "{{LABELS}}"
JUDGE_PROMPTS = ("judge_refusal", "judge_diff")


def format_labels(labels: list[str]) -> str:
    quoted = [f'"{label}"' for label in labels]
    if len(quoted) <= 2:
        return " or ".join(quoted)
    return ", ".join(quoted[:-1]) + ", or " + quoted[-1]


def prompt_sha256(system: str, messages: list[dict[str, Any]]) -> str:
    return sha256_text(canonical_json({"system": system, "messages": messages}))


class PromptBook:
    """System prompts for every task, rendered once from prompts/<family>.txt."""

    def __init__(self, prompts_dir: Path, tasks: dict[str, TaskSpec]):
        self.prompts_dir = prompts_dir
        self.tasks = tasks
        self.systems: dict[str, str] = {}
        for task, spec in tasks.items():
            template = self.read(spec.family)
            if template.count(PLACEHOLDER) != 1:
                raise ValueError(f"prompts/{spec.family}.txt must contain {PLACEHOLDER} exactly once")
            self.systems[task] = template.replace(PLACEHOLDER, format_labels(spec.labels))

    def read(self, name: str) -> str:
        path = self.prompts_dir / f"{name}.txt"
        if not path.exists():
            raise SystemExit(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    def labels(self, task: str) -> list[str]:
        return self.tasks[task].labels

    def request(self, case: Case, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        """The full request for one case under one arm's parameters, and its prompt hash."""
        if case.task not in self.systems:
            raise SystemExit(f"Task {case.task!r} has no entry in the task file; add its family and labels.")
        system = self.systems[case.task]
        messages = [{"role": "user", "content": case.input}]
        return {**params, "system": system, "messages": messages}, prompt_sha256(system, messages)

    def digest(self) -> dict[str, str]:
        """SHA-256 of every prompt file in use, for freezing into a run's config."""
        names = sorted({spec.family for spec in self.tasks.values()} | set(JUDGE_PROMPTS))
        return {f"{name}.txt": sha256_file(self.prompts_dir / f"{name}.txt") for name in names}
