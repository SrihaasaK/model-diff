"""Comparisons the report builds from final answers: pair statistics, direction of change, attribution steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Config
from ..score.metrics import PARSE_FAIL, REFUSAL, FinalAnswer
from ..score.stats import mcnemar_exact

# Direction of change: a task's changes lean one way only when at least MIN_DIRECTIONAL of them
# cross the flag boundary and at least DOMINANT_SHARE of those cross it the same way.
MIN_DIRECTIONAL = 5
DOMINANT_SHARE = 2 / 3
NO_LABEL = (PARSE_FAIL, REFUSAL)


def model_only_pair(cfg: Config, arms: list[str]) -> tuple[str, str] | None:
    """The step on the attribution path that changes only the model, if both of its arms completed."""
    d = cfg.decomposition
    if not d:
        return None
    for factor, x, y in zip(d.factors, d.path, d.path[1:]):
        if factor == "model" and x in arms and y in arms:
            return x, y
    return None


@dataclass
class PairStats:
    n_cases: int
    changed: int  # final answers differ
    label_changes: int  # both sides gave a label, and the labels differ
    no_label_changes: int  # one side gave no parseable label (or refused) and the other did
    only_base_right: int
    only_other_right: int

    @property
    def mcnemar_p(self) -> float:
        return mcnemar_exact(self.only_base_right, self.only_other_right)


def pair_stats(answers: dict[tuple[str, str], FinalAnswer], base: str, other: str, task: str | None = None) -> PairStats:
    pairs = [
        (a, answers[(other, case_id)])
        for (arm, case_id), a in answers.items()
        if arm == base and (task is None or a.task == task)
    ]
    changed = [(a, b) for a, b in pairs if a.outcome != b.outcome]
    return PairStats(
        n_cases=len(pairs),
        changed=len(changed),
        label_changes=sum(a.outcome not in NO_LABEL and b.outcome not in NO_LABEL for a, b in changed),
        no_label_changes=sum((a.outcome in NO_LABEL) != (b.outcome in NO_LABEL) for a, b in changed),
        only_base_right=sum(a.correct and not b.correct for a, b in pairs),
        only_other_right=sum(b.correct and not a.correct for a, b in pairs),
    )


def direction(answers: dict[tuple[str, str], FinalAnswer], base: str, other: str, task: str, positive: set[str]) -> dict:
    """How a task's changed answers move relative to its flag labels, and what that adds up to."""
    toward = away = lateral = no_label = 0
    for (arm, case_id), a in answers.items():
        if arm != base or a.task != task:
            continue
        b = answers[(other, case_id)]
        if a.outcome == b.outcome:
            continue
        if a.outcome in NO_LABEL or b.outcome in NO_LABEL:
            no_label += 1
        elif (b.outcome in positive) and (a.outcome not in positive):
            toward += 1
        elif (a.outcome in positive) and (b.outcome not in positive):
            away += 1
        else:
            lateral += 1
    crossing = toward + away
    if crossing < MIN_DIRECTIONAL:
        call = "too few changes to call"
    elif toward >= DOMINANT_SHARE * crossing:
        call = "more flags"
    elif away >= DOMINANT_SHARE * crossing:
        call = "fewer flags"
    else:
        call = "mixed"
    return {"toward": toward, "away": away, "lateral": lateral, "no_label": no_label, "call": call}


def reading(call: str, stricter_when: str | None) -> str:
    """Stricter or more lenient, where the task file says which way is stricter."""
    if call not in ("more flags", "fewer flags") or stricter_when is None:
        return call
    stricter = (call == "more flags") == (stricter_when == "more_flags")
    return "stricter" if stricter else "more lenient"


def _value(params: dict, key: str) -> str:
    if key not in params:
        return "not sent (API default)"
    value = params[key]
    return f"{value['type']}" if isinstance(value, dict) and "type" in value else str(value)


def param_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Every request parameter that differs between two arms, as 'key: old → new'."""
    keys = sorted(set(before) | set(after))
    return [f"{k}: {_value(before, k)} → {_value(after, k)}" for k in keys if before.get(k) != after.get(k)]
