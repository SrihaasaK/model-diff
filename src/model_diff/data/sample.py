"""Seeded, per-task case sampling.

Each task draws from its own generator seeded with "<seed>:<task>", so adding
or removing a task never changes another task's sample. Pools are sorted by
case_id before drawing, so the sample does not depend on source order.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

from .cases import Case
from .tasks import TaskSpec


def _random(cases: list[Case], k: int, rng: random.Random) -> list[Case]:
    return rng.sample(cases, min(k, len(cases)))


def _stratified(cases: list[Case], k: int, rng: random.Random) -> list[Case]:
    """Equal shares per gold label; a label with too few cases gives its spare slots to the rest."""
    by_label: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        by_label[case.gold_label].append(case)
    quota = {label: 0 for label in by_label}
    remaining = min(k, len(cases))
    while remaining:
        for label in sorted(by_label):
            if remaining and quota[label] < len(by_label[label]):
                quota[label] += 1
                remaining -= 1
    picked = []
    for label in sorted(by_label):
        picked += rng.sample(by_label[label], quota[label])
    return picked


def sample_cases(pool: list[Case], specs: dict[str, TaskSpec], per_task: int, seed: int) -> list[Case]:
    by_task: dict[str, list[Case]] = defaultdict(list)
    for case in pool:
        by_task[case.task].append(case)
    sampled: list[Case] = []
    for task in sorted(by_task):
        cases = sorted(by_task[task], key=lambda c: c.case_id)
        rng = random.Random(f"{seed}:{task}")
        strategy = specs[task].sampling if task in specs else "random"
        draw = _stratified if strategy == "stratified" else _random
        sampled += draw(cases, per_task, rng)
    return sorted(sampled, key=lambda c: (c.task, c.case_id))


def summarize(cases: list[Case]) -> dict[str, dict]:
    """Per-task case counts and gold-label counts."""
    summary: dict[str, dict] = {}
    for task in sorted({c.task for c in cases}):
        task_cases = [c for c in cases if c.task == task]
        summary[task] = {
            "n": len(task_cases),
            "labels": dict(sorted(Counter(c.gold_label for c in task_cases).items())),
        }
    return summary
