"""The score, diff, and report steps over a run directory.

Each step reads only the run directory (verified first) and writes its outputs
beside the records. The judge, when a step needs it, records its calls in the
same hash chain.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .diff.describe import describe
from .diff.differ import decompose, diff_answers, final_disagreement, review_sample, single_run_disagreement
from .judge import Judge
from .record.recorder import Recorder
from .report.report import build
from .runner import write_json
from .score.metrics import ALL_TASKS, compute_metrics, latency_samples
from .score.refusal import refusal_decisions
from .score.scoring import REFUSALS, RunData, answers_for, load_refusals, load_run, refusal_summary, write_final_answers

DIFF_COLUMNS = ["case_id", "task", "gold", "a_answer", "b_answer", "category", "judge_nature", "judge_sentence",
                "a_votes", "b_votes", "a_format_ok", "b_format_ok", "a_response", "b_response"]
SAMPLE_COLUMNS = ["case_id", "task", "category", "gold", "a_answer", "b_answer", "judge_nature", "judge_sentence",
                  "input", "a_response", "b_response", "human_verdict", "notes"]


def score_run(run_dir: Path, client: Any | None, echo: Callable[[str], None] = print) -> dict:
    """Decide refusals, compute metrics, and write refusals.json, scores.json, and final_answers.csv."""
    data = load_run(run_dir)
    if data.state.get("status") != "complete":
        echo(f"Note: run status is {data.state.get('status')!r}; scoring what was recorded.")
    recorder = Recorder(run_dir)
    judge = Judge(data.cfg, client, recorder, run_dir / "prompts", echo)
    decisions = refusal_decisions(data.subject_records(), data.labels, judge)
    write_json(run_dir / REFUSALS, {"decisions": decisions, "summary": refusal_summary(decisions)})

    observations, answers = answers_for(data, decisions)
    latencies = latency_samples([r for r in data.records if r.arm in data.arms])
    metrics = compute_metrics(answers, observations, latencies, data.labels, data.positive, data.natural_shares())
    scores = {
        "run_id": data.run_config["run_id"],
        "kept_arms": data.arms,
        "dropped_arms": data.state.get("dropped_arms", []),
        "completeness": data.completeness(),
        "refusals": refusal_summary(decisions),
        "judge": {"asked_now": judge.asked, "not_judged": judge.skipped, "spent_usd": judge.spent},
        "chain_head": recorder.head,
        "metrics": [m.to_dict() for m in metrics],
    }
    write_json(run_dir / "scores.json", scores)
    write_final_answers(run_dir / "final_answers.csv", answers)
    return scores


def _pair_summary(answers: dict, x: str, y: str) -> dict:
    rows = diff_answers(answers, x, y)
    by_task: dict[str, Counter] = {}
    for r in rows:
        by_task.setdefault(r.task, Counter())[r.category] += 1
    return {
        "categories": dict(Counter(r.category for r in rows)),
        "categories_by_task": {t: dict(c) for t, c in sorted(by_task.items())},
        "final_disagreement": final_disagreement(answers, x, y),
        "single_run_disagreement": single_run_disagreement(answers, x, y),
    }


def attribution_path(data: RunData) -> tuple[list[str], list[str]] | None:
    """The decomposition path over the arms that completed; a step across a dropped arm carries every factor it spans."""
    if not data.cfg.decomposition:
        return None
    path, factors = data.cfg.decomposition.path, data.cfg.decomposition.factors
    kept = [i for i, arm in enumerate(path) if arm in data.arms]
    return [path[i] for i in kept], ["+".join(factors[i:j]) for i, j in zip(kept, kept[1:])]


def diff_run(run_dir: Path, client: Any | None, echo: Callable[[str], None] = print) -> dict:
    """Compare the headline arms, describe each change with the judge, attribute it, and write the diff files."""
    data = load_run(run_dir)
    _, answers = answers_for(data, load_refusals(run_dir))
    base, other = data.run_config["headline"]
    rows = diff_answers(answers, base, other)
    recorder = Recorder(run_dir)
    judge = Judge(data.cfg, client, recorder, run_dir / "prompts", echo)
    cases = {c.case_id: c for c in data.cases}
    describe(rows, cases, data.tasks, judge, (base, other))

    pd.DataFrame([r.to_dict() for r in rows])[DIFF_COLUMNS].to_csv(run_dir / "diffs.csv", index=False)
    sample = [
        {**r.to_dict(), "input": cases[r.case_id].input, "human_verdict": "", "notes": ""}
        for r in review_sample(rows, n=30, seed=data.cfg.seed)
    ]
    pd.DataFrame(sample, columns=SAMPLE_COLUMNS).to_csv(run_dir / "diffs_sample_for_review.csv", index=False)

    pairs = {f"{base}>{other}": _pair_summary(answers, base, other)}
    attribution = None
    path = attribution_path(data)
    if path:
        arms, factors = path
        attribution = decompose(answers, arms, factors)
        for x, y in zip(arms, arms[1:]):
            pairs[f"{x}>{y}"] = _pair_summary(answers, x, y)
    summary = {
        "headline": [base, other],
        "pairs": pairs,
        "attribution": attribution,
        "judge_natures": dict(Counter(r.judge_nature for r in rows if r.category != "same")),
        "judge": {"asked_now": judge.asked, "not_judged": judge.skipped, "spent_usd_total": judge.spent},
        "chain_head": recorder.head,
    }
    write_json(run_dir / "diff_summary.json", summary)
    return summary


def report_run(run_dir: Path) -> Path:
    """Write report.md and its two charts. Makes no API call."""
    data = load_run(run_dir)
    for name in ("scores.json", "diff_summary.json"):
        if not (run_dir / name).exists():
            raise SystemExit(f"{name} not found. Run `model-diff score` and `model-diff diff` first.")
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "diff_summary.json").read_text(encoding="utf-8"))
    _, answers = answers_for(data, load_refusals(run_dir))
    out = run_dir / "report.md"
    out.write_text(build(data, scores, summary, answers, run_dir), encoding="utf-8")
    return out


def headline_lines(scores: dict, summary: dict) -> list[str]:
    """A short terminal summary of what score and diff found."""
    base, other = summary["headline"]
    metrics = {(m["arm"], m["task"]): m for m in scores["metrics"]}
    lines = [f"{'arm':<4} {'accuracy':>8} {'95% CI':>15} {'parse fail':>10} {'refusal':>8} {'noise floor':>11}"]
    for arm in scores["kept_arms"]:
        m = metrics[(arm, ALL_TASKS)]
        ci = f"{m['accuracy_ci95'][0]:.3f}-{m['accuracy_ci95'][1]:.3f}"
        lines.append(f"{arm:<4} {m['accuracy']:>8.3f} {ci:>15} {m['parse_failure_rate']:>10.3f} {m['refusal_rate']:>8.3f} {m['noise_floor']:>11.3f}")
    headline = summary["pairs"][f"{base}>{other}"]
    lines.append(f"{base} vs {other}: final answers differ on {headline['final_disagreement'][ALL_TASKS]:.1%} of cases.")
    lines += [f"  {c:<24} {n:>4}" for c, n in sorted(headline["categories"].items(), key=lambda kv: -kv[1])]
    attribution = summary.get("attribution")
    if attribution:
        lines.append(f"Sequential attribution along {' -> '.join(attribution['path'])} ({attribution['n_changed']} changed cases):")
        lines += [
            f"  {f:<20} alone {attribution['only'][f]:>4}   involved {attribution['involved'][f]:>4}"
            for f in attribution["only"]
        ]
    return lines
