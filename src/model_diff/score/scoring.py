"""Load a run directory and turn its records into final answers and metrics.

Shared by the score, diff, and report commands. Everything is read from the run
directory's frozen copies, and the hash chain is verified before anything is
scored, so a tampered run is never reported on.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..config import Config, load_config
from ..data.cases import Case, read_cases
from ..data.tasks import TaskSpec, load_tasks
from ..record.chain import verify_run
from ..record.recorder import RUN_CONFIG
from ..record.schema import CallRecord
from .metrics import FinalAnswer, Observation, final_answers, observations_from_records

REFUSALS = "refusals.json"


@dataclass
class RunData:
    run_dir: Path
    cfg: Config  # the config frozen when the run started
    run_config: dict
    state: dict
    tasks: dict[str, TaskSpec]
    cases: list[Case]
    records: list[CallRecord]
    head: str

    @property
    def arms(self) -> list[str]:
        """Arms that completed the run. Dropped arms have pilot data only and are not scored."""
        return list(self.state.get("kept_arms", self.run_config["arms"]))

    @property
    def gold(self) -> dict[str, str]:
        return {c.case_id: c.gold_label for c in self.cases}

    @property
    def labels(self) -> dict[str, list[str]]:
        return {task: spec.labels for task, spec in self.tasks.items()}

    @property
    def positive(self) -> dict[str, set[str]]:
        return {task: set(spec.positive_labels) for task, spec in self.tasks.items()}

    def natural_shares(self) -> dict[str, dict[str, float]]:
        """Source label shares for tasks sampled stratified, from the full split recorded at sampling time."""
        pool = json.loads((self.run_dir / "cases.meta.json").read_text(encoding="utf-8"))["pool"]
        shares = {}
        for task, spec in self.tasks.items():
            if spec.sampling == "stratified":
                counts = pool[task]["labels"]
                total = sum(counts.values())
                shares[task] = {label: n / total for label, n in counts.items()}
        return shares

    def subject_records(self) -> list[CallRecord]:
        return [r for r in self.records if r.kind == "subject" and r.arm in self.arms]

    def completeness(self) -> dict[str, dict[str, int]]:
        expected = len(self.cases) * self.run_config["n_runs"]
        out = {}
        for arm in self.arms:
            recs = [r for r in self.records if r.kind == "subject" and r.arm == arm]
            out[arm] = {
                "expected_calls": expected,
                "recorded_calls": sum(r.error is None for r in recs),
                "failed_calls": sum(r.error is not None for r in recs),
            }
        return out


def load_run(run_dir: Path) -> RunData:
    if not run_dir.is_dir():
        raise SystemExit(f"No run directory at {run_dir}")
    result = verify_run(run_dir)
    if not result.ok:
        raise SystemExit("The run's records fail verification:\n  " + "\n  ".join(result.problems))
    state_path = run_dir / "state.json"
    records = [CallRecord.model_validate_json(line) for line in (run_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    return RunData(
        run_dir=run_dir,
        cfg=load_config(run_dir / "config.yaml"),
        run_config=json.loads((run_dir / RUN_CONFIG).read_text(encoding="utf-8")),
        state=json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {},
        tasks=load_tasks(run_dir / "tasks.yaml").tasks,
        cases=read_cases(run_dir / "cases.jsonl"),
        records=records,
        head=result.head,
    )


def load_refusals(run_dir: Path) -> dict[str, dict]:
    path = run_dir / REFUSALS
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `model-diff score {run_dir.name}` first.")
    return json.loads(path.read_text(encoding="utf-8"))["decisions"]


def answers_for(data: RunData, decisions: dict[str, dict]) -> tuple[list[Observation], dict[tuple[str, str], FinalAnswer]]:
    refusals = {key: d["refusal"] for key, d in decisions.items()}
    observations = observations_from_records(data.subject_records(), refusals)
    return observations, final_answers(observations, data.gold)


def refusal_summary(decisions: dict[str, dict]) -> dict:
    by_arm: dict[str, Counter] = {}
    for key, decision in decisions.items():
        arm = key.split("|", 1)[0]
        counter = by_arm.setdefault(arm, Counter())
        counter[f"{decision['source']}_{'refusal' if decision['refusal'] else 'not_refusal'}"] += 1
    return {arm: dict(sorted(c.items())) for arm, c in sorted(by_arm.items())}


def write_final_answers(path: Path, answers: dict[tuple[str, str], FinalAnswer]) -> None:
    rows = [
        {
            "arm": a.arm, "case_id": a.case_id, "task": a.task, "gold": a.gold, "outcome": a.outcome,
            "correct": a.correct, "votes": "|".join(a.votes), "unanimous": a.unanimous,
            "format_ok_majority": a.format_ok_majority,
        }
        for a in sorted(answers.values(), key=lambda a: (a.arm, a.task, a.case_id))
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
