"""Compare model A's and model B's final answers case by case."""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import product
from statistics import mean

from ..score.metrics import ALL_TASKS, PARSE_FAIL, REFUSAL, FinalAnswer

CATEGORIES = (
    "same",
    "A_right_B_wrong",
    "A_wrong_B_right",
    "both_wrong_differently",
    "format_drift",
    "refusal_change",
)


def classify(a: FinalAnswer, b: FinalAnswer) -> str:
    """Category of the change from A's final answer to B's.

    Precedence: a refusal on one side only is refusal_change; otherwise an
    unparseable answer on one side only is format_drift. Equal labels are
    same, unless one model's repeats mostly broke the strict JSON format and
    the other's did not, which is also format_drift. Different labels are
    judged against gold.
    """
    if (a.outcome == REFUSAL) != (b.outcome == REFUSAL):
        return "refusal_change"
    if (a.outcome == PARSE_FAIL) != (b.outcome == PARSE_FAIL):
        return "format_drift"
    if a.outcome == b.outcome:
        is_label = a.outcome not in (REFUSAL, PARSE_FAIL)
        if is_label and a.format_ok_majority != b.format_ok_majority:
            return "format_drift"
        return "same"
    if a.outcome == a.gold:
        return "A_right_B_wrong"
    if b.outcome == b.gold:
        return "A_wrong_B_right"
    return "both_wrong_differently"


@dataclass
class DiffRow:
    case_id: str
    task: str
    gold: str
    a_answer: str
    b_answer: str
    a_votes: str
    b_votes: str
    category: str
    a_format_ok: bool
    b_format_ok: bool
    a_response: str
    b_response: str
    judge_nature: str = ""
    judge_sentence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def diff_answers(answers: dict[tuple[str, str], FinalAnswer]) -> list[DiffRow]:
    case_ids = sorted({case_id for _, case_id in answers})
    missing = [c for c in case_ids if ("model_a", c) not in answers or ("model_b", c) not in answers]
    if missing:
        raise ValueError(f"{len(missing)} cases lack an answer from one model, e.g. {missing[:3]}")
    rows = []
    for case_id in case_ids:
        a, b = answers[("model_a", case_id)], answers[("model_b", case_id)]
        rows.append(
            DiffRow(
                case_id=case_id,
                task=a.task,
                gold=a.gold,
                a_answer=a.outcome,
                b_answer=b.outcome,
                a_votes="|".join(a.votes),
                b_votes="|".join(b.votes),
                category=classify(a, b),
                a_format_ok=a.format_ok_majority,
                b_format_ok=b.format_ok_majority,
                a_response=a.representative,
                b_response=b.representative,
            )
        )
    return rows


def cross_model_disagreement(answers: dict[tuple[str, str], FinalAnswer]) -> dict[str, float]:
    """Mean share of (A repeat, B repeat) pairs that disagree, by task and pooled.

    This is the cross-model counterpart of each model's noise floor: if it is
    no higher than the noise floors, single runs of A and B disagree about as
    often as two runs of the same model do.
    """
    shares: dict[str, list[float]] = defaultdict(list)
    for (role, case_id), a in answers.items():
        if role != "model_a" or ("model_b", case_id) not in answers:
            continue
        b = answers[("model_b", case_id)]
        pairs = list(product(a.votes, b.votes))
        share = sum(x != y for x, y in pairs) / len(pairs)
        shares[a.task].append(share)
        shares[ALL_TASKS].append(share)
    return {task: mean(values) for task, values in shares.items()}


def allocate(sizes: dict[str, int], n: int) -> dict[str, int]:
    """Split n slots across groups: one per non-empty group, the rest by largest remainder."""
    if sum(sizes.values()) <= n:
        return dict(sizes)
    nonempty = sorted(k for k, v in sizes.items() if v > 0)
    base = {k: 1 for k in nonempty} if n >= len(nonempty) else {}
    capacity = {k: sizes[k] - base.get(k, 0) for k in nonempty}
    remaining = n - sum(base.values())
    total_capacity = sum(capacity.values())
    quotas = {k: remaining * capacity[k] / total_capacity for k in nonempty}
    extra = {k: min(capacity[k], int(quotas[k])) for k in nonempty}
    leftover = remaining - sum(extra.values())
    order = sorted(nonempty, key=lambda k: (-(quotas[k] - int(quotas[k])), k))
    i = 0
    while leftover > 0:
        k = order[i % len(order)]
        if extra[k] < capacity[k]:
            extra[k] += 1
            leftover -= 1
        i += 1
    return {k: base.get(k, 0) + extra.get(k, 0) for k in sizes}


def _spread_across_tasks(rows: list[DiffRow], k: int, rng: random.Random) -> list[DiffRow]:
    by_task: dict[str, list[DiffRow]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: (r.task, r.case_id)):
        by_task[row.task].append(row)
    for group in by_task.values():
        rng.shuffle(group)
    picked: list[DiffRow] = []
    while len(picked) < k and any(by_task.values()):
        for task in sorted(by_task):
            if by_task[task] and len(picked) < k:
                picked.append(by_task[task].pop())
    return picked


def review_sample(rows: list[DiffRow], n: int = 30, seed: int = 42) -> list[DiffRow]:
    """A seeded sample of differing cases, stratified by category and spread across tasks.

    With fewer than n differing cases, all of them are taken and the rest of
    the sample is filled with unchanged cases as controls.
    """
    rng = random.Random(seed)
    differing = [r for r in rows if r.category != "same"]
    if len(differing) <= n:
        chosen = list(differing)
        chosen += _spread_across_tasks([r for r in rows if r.category == "same"], n - len(chosen), rng)
    else:
        by_category: dict[str, list[DiffRow]] = defaultdict(list)
        for row in differing:
            by_category[row.category].append(row)
        quota = allocate({c: len(v) for c, v in by_category.items()}, n)
        chosen = []
        for category in sorted(by_category):
            chosen += _spread_across_tasks(by_category[category], quota[category], rng)
    return sorted(chosen, key=lambda r: (CATEGORIES.index(r.category), r.task, r.case_id))
