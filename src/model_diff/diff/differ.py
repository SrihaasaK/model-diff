"""Compare two arms' final answers case by case, and attribute the headline change to factors.

In a pair (base, other), "A" in the category names means the base arm and "B"
the other arm; for the headline pair they are literally arms A and B.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
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

Answers = dict[tuple[str, str], FinalAnswer]


def classify(a: FinalAnswer, b: FinalAnswer) -> str:
    """Category of the change from the base answer a to the other answer b.

    Precedence: a refusal on one side only is refusal_change; otherwise an
    unparseable answer on one side only is format_drift. Equal labels are
    same, unless one side's repeats mostly broke the strict JSON format and
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


def _paired_cases(answers: Answers, arms: list[str]) -> list[str]:
    case_ids = sorted({case_id for arm, case_id in answers if arm in arms})
    missing = [c for c in case_ids if any((arm, c) not in answers for arm in arms)]
    if missing:
        raise ValueError(f"{len(missing)} cases lack an answer from one of {arms}, e.g. {missing[:3]}")
    return case_ids


def diff_answers(answers: Answers, base: str, other: str) -> list[DiffRow]:
    rows = []
    for case_id in _paired_cases(answers, [base, other]):
        a, b = answers[(base, case_id)], answers[(other, case_id)]
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


def _by_task(values: list[tuple[str, float]]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for task, value in values:
        grouped[task].append(value)
        grouped[ALL_TASKS].append(value)
    return {task: mean(v) for task, v in grouped.items()}


def final_disagreement(answers: Answers, base: str, other: str) -> dict[str, float]:
    """Share of cases whose final (majority) answers differ, by task and pooled."""
    return _by_task(
        [
            (answers[(base, c)].task, float(answers[(base, c)].outcome != answers[(other, c)].outcome))
            for c in _paired_cases(answers, [base, other])
        ]
    )


def single_run_disagreement(answers: Answers, base: str, other: str) -> dict[str, float]:
    """Mean share of (base repeat, other repeat) pairs that disagree, by task and pooled.

    This is the cross-arm counterpart of each arm's noise floor: if it is no
    higher than the noise floors, single runs of the two arms disagree about as
    often as two runs of the same arm do.
    """
    values = []
    for c in _paired_cases(answers, [base, other]):
        a, b = answers[(base, c)], answers[(other, c)]
        pairs = list(product(a.votes, b.votes))
        values.append((a.task, sum(x != y for x, y in pairs) / len(pairs)))
    return _by_task(values)


def decompose(answers: Answers, path: list[str], factors: list[str]) -> dict:
    """Attribute cases where the first and last arms' final answers differ to the steps between them.

    Each step along the path changes one factor. For every case whose answer
    differs between path[0] and path[-1], the steps whose two arms give
    different final answers are the factors that moved it. A factor "explains"
    a case alone when it is the only step that changed; it is "involved" when
    its step changed along with others. Steps can also change an answer and
    change it back; such cases do not count toward the first-to-last change.
    """
    case_ids = _paired_cases(answers, path)
    changed_cases = [c for c in case_ids if answers[(path[0], c)].outcome != answers[(path[-1], c)].outcome]
    only: Counter[str] = Counter()
    involved: Counter[str] = Counter()
    combinations: Counter[str] = Counter()
    for c in changed_cases:
        moved = [
            factor
            for factor, (x, y) in zip(factors, zip(path, path[1:]))
            if answers[(x, c)].outcome != answers[(y, c)].outcome
        ]
        combinations["+".join(moved)] += 1
        involved.update(moved)
        if len(moved) == 1:
            only[moved[0]] += 1
    steps = [
        {
            "factor": factor,
            "from": x,
            "to": y,
            "final_disagreement": final_disagreement(answers, x, y)[ALL_TASKS],
            "single_run_disagreement": single_run_disagreement(answers, x, y)[ALL_TASKS],
        }
        for factor, (x, y) in zip(factors, zip(path, path[1:]))
    ]
    return {
        "path": path,
        "n_cases": len(case_ids),
        "n_changed": len(changed_cases),
        "steps": steps,
        "only": {f: only[f] for f in factors},
        "involved": {f: involved[f] for f in factors},
        "combinations": dict(sorted(combinations.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


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


def equal_share_sample(rows: list[DiffRow], categories: list[str], per_category: int, n: int, seed: int) -> list[DiffRow]:
    """Up to per_category rows from each category, spread across tasks; spare slots go round-robin.

    A category with fewer rows than its share gives its spare slots to the
    others, one at a time in category order, until n rows are taken or none remain.
    Unchanged ("same") cases are never added.
    """
    rng = random.Random(seed)
    pools = {c: _spread_across_tasks([r for r in rows if r.category == c], len(rows), rng) for c in categories}
    quota = {c: min(per_category, len(pools[c])) for c in categories}
    while sum(quota.values()) < n and any(quota[c] < len(pools[c]) for c in categories):
        for c in categories:
            if sum(quota.values()) < n and quota[c] < len(pools[c]):
                quota[c] += 1
    chosen = [row for c in categories for row in pools[c][: quota[c]]]
    return sorted(chosen, key=lambda r: (CATEGORIES.index(r.category), r.task, r.case_id))


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
