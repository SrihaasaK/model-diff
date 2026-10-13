"""Task specifications: data/tasks.yaml describes each task the harness runs.

The file also carries the approval gate. Nothing that samples cases or spends
money runs until a person has reviewed data/TASKS.md and set approved: true.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class TaskSpec(BaseModel):
    family: str  # selects prompts/<family>.md
    labels: list[str]
    positive_labels: list[str] = Field(default_factory=list)  # labels counted as a "flag"
    domain: str = ""
    justification: str = ""
    license: str = ""
    license_url: str = ""
    label_map: dict[str, str] = Field(default_factory=dict)  # dataset label -> label shown to the model
    input_fields: list[tuple[str, str]] = Field(default_factory=list)  # (dataset column, heading or "")
    sampling: Literal["random", "stratified"] = "random"
    # Which way is "stricter" for this task: more flags (e.g. more violations found) or fewer
    # (e.g. fewer claims covered). Unset when a flag is not an adverse finding.
    stricter_when: Literal["more_flags", "fewer_flags"] | None = None

    @model_validator(mode="after")
    def _labels_are_consistent(self) -> "TaskSpec":
        unknown = set(self.positive_labels) - set(self.labels)
        unknown |= set(self.label_map.values()) - set(self.labels)
        if unknown:
            raise ValueError(f"labels not in the task's label set: {sorted(unknown)}")
        return self


class TaskFile(BaseModel):
    approved: bool = False
    approved_on: str | None = None
    tasks: dict[str, TaskSpec]
    screened_out: list[dict[str, str]] = Field(default_factory=list)


def load_tasks(path: Path) -> TaskFile:
    if not path.exists():
        raise SystemExit(f"Task file not found: {path}")
    return TaskFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def require_approval(task_file: TaskFile, path: Path) -> None:
    if not task_file.approved:
        raise SystemExit(
            f"{path} is not approved. Review data/TASKS.md, then set 'approved: true' "
            "(and approved_on) in the task file."
        )
