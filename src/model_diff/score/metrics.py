"""Per-arm, per-task metrics from scored call records.

Each subject call becomes an Observation with one outcome: an allowed label,
REFUSAL, or PARSE_FAIL. An arm's final answer for a case is the majority
outcome across its repeats; refusals and parse failures can win the vote and
always count as wrong.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from statistics import mean
from typing import Callable

from ..record.schema import JUDGE, CallRecord
from .stats import wilson_interval

REFUSAL = "<REFUSAL>"
PARSE_FAIL = "<PARSE_FAIL>"
ALL_TASKS = "ALL"


@dataclass(frozen=True)
class Observation:
    arm: str
    model_id: str
    task: str
    case_id: str
    repeat_index: int
    label: str | None
    parse_ok: bool
    format_ok: bool
    refusal: bool
    raw_response: str
    input_tokens: int
    output_tokens: int
    thinking_tokens: int | None

    @property
    def outcome(self) -> str:
        if self.refusal:
            return REFUSAL
        if not self.parse_ok or self.label is None:
            return PARSE_FAIL
        return self.label


@dataclass(frozen=True)
class FinalAnswer:
    arm: str
    model_id: str
    task: str
    case_id: str
    gold: str
    outcome: str
    votes: tuple[str, ...]  # outcomes in repeat order
    format_ok_majority: bool
    representative: str  # raw response of the earliest repeat that voted for the outcome

    @property
    def correct(self) -> bool:
        return self.outcome == self.gold

    @property
    def unanimous(self) -> bool:
        return len(set(self.votes)) == 1


def observations_from_records(records: list[CallRecord], refusals: dict[str, bool]) -> list[Observation]:
    """Scored subject calls. refusals maps subject keys to the refusal decision;
    a call missing from it is a refusal only if the API stopped with "refusal"."""
    out = []
    for rec in records:
        if rec.kind != "subject" or rec.error is not None:
            continue
        refusal = refusals.get(rec.subject_key(), rec.stop_reason == "refusal")
        out.append(
            Observation(
                arm=rec.arm,
                model_id=rec.model_id,
                task=rec.task,
                case_id=rec.case_id,
                repeat_index=rec.repeat_index,
                label=rec.parsed_label,
                parse_ok=rec.parse_ok,
                format_ok=rec.format_ok,
                refusal=refusal,
                raw_response=rec.raw_response,
                input_tokens=rec.input_tokens,
                output_tokens=rec.output_tokens,
                thinking_tokens=rec.thinking_tokens,
            )
        )
    return out


def latency_samples(records: list[CallRecord]) -> dict[tuple[str, str], list[float]]:
    """Latencies by (arm, task) from every successful direct call to a subject model."""
    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    for rec in records:
        if rec.arm != JUDGE and rec.kind in ("subject", "latency_probe"):
            if rec.latency_ms is not None and rec.error is None:
                samples[(rec.arm, rec.task)].append(rec.latency_ms)
    return samples


def majority_vote(votes: list[tuple[int, str]]) -> str:
    """Most frequent outcome; a tie goes to the tied outcome seen in the earliest repeat."""
    counts = Counter(outcome for _, outcome in votes)
    top = max(counts.values())
    tied = {outcome for outcome, count in counts.items() if count == top}
    for _, outcome in sorted(votes):
        if outcome in tied:
            return outcome
    raise ValueError("no votes")


def final_answers(observations: list[Observation], gold: dict[str, str]) -> dict[tuple[str, str], FinalAnswer]:
    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for obs in observations:
        grouped[(obs.arm, obs.case_id)].append(obs)
    answers = {}
    for (arm, case_id), group in grouped.items():
        group.sort(key=lambda o: o.repeat_index)
        outcome = majority_vote([(o.repeat_index, o.outcome) for o in group])
        representative = next(o.raw_response for o in group if o.outcome == outcome)
        answers[(arm, case_id)] = FinalAnswer(
            arm=arm,
            model_id=group[0].model_id,
            task=group[0].task,
            case_id=case_id,
            gold=gold[case_id],
            outcome=outcome,
            votes=tuple(o.outcome for o in group),
            format_ok_majority=2 * sum(o.format_ok for o in group) > len(group),
            representative=representative,
        )
    return answers


def reweighted_rate(answers: list[FinalAnswer], shares: dict[str, float], hit: Callable[[FinalAnswer], bool]) -> float | None:
    """A rate post-stratified to a gold-label distribution.

    Computes the rate within each gold label, then weights it by that label's
    share. Labels with no sampled case are dropped and the remaining shares
    renormalized.
    """
    by_gold: dict[str, list[FinalAnswer]] = defaultdict(list)
    for ans in answers:
        by_gold[ans.gold].append(ans)
    present = {label: share for label, share in shares.items() if by_gold.get(label)}
    total = sum(present.values())
    if not total:
        return None
    return sum(share * mean(hit(a) for a in by_gold[label]) for label, share in present.items()) / total


@dataclass
class GroupMetrics:
    arm: str
    model_id: str
    task: str  # a task name, or ALL for every case pooled
    n_cases: int
    n_calls: int
    correct: int
    accuracy: float
    accuracy_ci95: tuple[float, float]
    flag_rate: float | None  # share of cases whose final answer is a positive label
    flag_rate_natural: float | None  # flag rate reweighted to the source's label mix (stratified tasks)
    accuracy_natural: float | None  # accuracy reweighted the same way
    parse_failure_rate: float  # per call: no allowed label could be recovered (refusals excluded)
    format_violation_rate: float  # per call: not exactly the requested JSON object
    refusal_rate: float  # per call
    unanimity_rate: float  # share of cases where every repeat gave the same outcome
    pairwise_agreement: float  # mean share of agreeing repeat pairs per case
    noise_floor: float  # 1 - pairwise_agreement: chance two runs of this arm disagree on a case
    repeat_accuracies: list[float]  # accuracy of each repeat scored alone
    mean_latency_ms: float | None
    latency_samples: int
    mean_input_tokens: float
    mean_output_tokens: float
    mean_thinking_tokens: float | None
    total_input_tokens: int
    total_output_tokens: int
    per_label: dict[str, dict[str, float | int | None]] | None

    def to_dict(self) -> dict:
        return asdict(self)


def _pairwise_agreement(answers: list[FinalAnswer]) -> float:
    shares = []
    for ans in answers:
        pairs = list(combinations(ans.votes, 2))
        if pairs:
            shares.append(sum(a == b for a, b in pairs) / len(pairs))
    return mean(shares) if shares else 1.0


def _per_label(answers: list[FinalAnswer], labels: list[str]) -> dict[str, dict[str, float | int | None]]:
    table = {}
    for label in labels:
        predicted = sum(a.outcome == label for a in answers)
        support = sum(a.gold == label for a in answers)
        hits = sum(a.outcome == label and a.gold == label for a in answers)
        table[label] = {
            "precision": hits / predicted if predicted else None,
            "recall": hits / support if support else None,
            "predicted": predicted,
            "support": support,
        }
    return table


def _group(
    arm: str,
    task: str,
    answers: list[FinalAnswer],
    observations: list[Observation],
    latencies: list[float],
    positive: dict[str, set[str]],
    labels: list[str] | None,
    natural: dict[str, float] | None,
) -> GroupMetrics:
    n_cases = len(answers)
    n_calls = len(observations)
    correct = sum(a.correct for a in answers)

    def flagged(a: FinalAnswer) -> bool:
        return a.outcome in positive[a.task]

    flaggable = [a for a in answers if positive.get(a.task)]
    flag_rate = sum(flagged(a) for a in flaggable) / len(flaggable) if flaggable else None

    by_repeat: dict[int, list[Observation]] = defaultdict(list)
    gold = {a.case_id: a.gold for a in answers}
    for obs in observations:
        by_repeat[obs.repeat_index].append(obs)
    repeat_accuracies = [
        sum(o.outcome == gold[o.case_id] for o in obs_list) / len(obs_list)
        for _, obs_list in sorted(by_repeat.items())
    ]

    thinking = [o.thinking_tokens for o in observations if o.thinking_tokens is not None]
    agreement = _pairwise_agreement(answers)
    return GroupMetrics(
        arm=arm,
        model_id=answers[0].model_id,
        task=task,
        n_cases=n_cases,
        n_calls=n_calls,
        correct=correct,
        accuracy=correct / n_cases,
        accuracy_ci95=wilson_interval(correct, n_cases),
        flag_rate=flag_rate,
        flag_rate_natural=reweighted_rate(flaggable, natural, flagged) if natural and flaggable else None,
        accuracy_natural=reweighted_rate(answers, natural, lambda a: a.correct) if natural else None,
        parse_failure_rate=sum(o.outcome == PARSE_FAIL for o in observations) / n_calls,
        format_violation_rate=sum(not o.format_ok for o in observations) / n_calls,
        refusal_rate=sum(o.refusal for o in observations) / n_calls,
        unanimity_rate=sum(a.unanimous for a in answers) / n_cases,
        pairwise_agreement=agreement,
        noise_floor=1 - agreement,
        repeat_accuracies=repeat_accuracies,
        mean_latency_ms=mean(latencies) if latencies else None,
        latency_samples=len(latencies),
        mean_input_tokens=mean(o.input_tokens for o in observations),
        mean_output_tokens=mean(o.output_tokens for o in observations),
        mean_thinking_tokens=mean(thinking) if thinking else None,
        total_input_tokens=sum(o.input_tokens for o in observations),
        total_output_tokens=sum(o.output_tokens for o in observations),
        per_label=_per_label(answers, labels) if labels is not None else None,
    )


def compute_metrics(
    answers: dict[tuple[str, str], FinalAnswer],
    observations: list[Observation],
    latencies: dict[tuple[str, str], list[float]],
    labels: dict[str, list[str]],
    positive: dict[str, set[str]],
    natural: dict[str, dict[str, float]] | None = None,
) -> list[GroupMetrics]:
    """Metrics for every (arm, task) pair plus each arm pooled over all tasks.

    natural maps a task to its source label shares; tasks listed there also get
    reweighted flag rate and accuracy (used for tasks sampled stratified).
    """
    natural = natural or {}
    results = []
    arms = sorted({a.arm for a in answers.values()})
    tasks = sorted({a.task for a in answers.values()})
    for arm in arms:
        arm_answers = [a for a in answers.values() if a.arm == arm]
        arm_obs = [o for o in observations if o.arm == arm]
        for task in tasks:
            task_answers = [a for a in arm_answers if a.task == task]
            if not task_answers:
                continue
            results.append(
                _group(
                    arm,
                    task,
                    task_answers,
                    [o for o in arm_obs if o.task == task],
                    latencies.get((arm, task), []),
                    positive,
                    labels.get(task),
                    natural.get(task),
                )
            )
        pooled_latency = [ms for (a, _), values in latencies.items() if a == arm for ms in values]
        results.append(_group(arm, ALL_TASKS, arm_answers, arm_obs, pooled_latency, positive, None, None))
    return results
