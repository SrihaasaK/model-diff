"""The score, diff, and report steps over a run directory.

Each step reads only the run directory (verified first) and writes its outputs
beside the records. The judge, when a step needs it, records its calls in the
same hash chain.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .diff.describe import describe
from .diff.differ import (
    CATEGORIES,
    decompose,
    diff_answers,
    equal_share_sample,
    final_disagreement,
    review_sample,
    single_run_disagreement,
)
from .report.comparisons import model_only_pair

CHANGE_CATEGORIES = [c for c in CATEGORIES if c != "same"]
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
                  "input", "a_response", "b_response", "rule_label", "rule_note", "human_verdict", "notes"]
# Columns a reviewer fills in; they survive every rewrite of the sample file.
REVIEW_COLUMNS = ("rule_label", "rule_note", "human_verdict", "notes")


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

    # The review sample comes from the model-only pair when there is one, with equal shares per change category.
    review_pair = model_only_pair(data.cfg, data.arms)
    if review_pair:
        x, y = review_pair
        review_rows = diff_answers(answers, x, y)
        # Model-only changes get only descriptions already recorded (see describe_sample); none are asked here.
        describe(review_rows, cases, data.tasks, Judge(data.cfg, None, recorder, run_dir / "prompts", echo), review_pair)
        pd.DataFrame([r.to_dict() for r in review_rows])[DIFF_COLUMNS].to_csv(run_dir / f"diffs_{x}_vs_{y}.csv", index=False)
        picked = equal_share_sample(review_rows, CHANGE_CATEGORIES, per_category=6, n=30, seed=data.cfg.seed)
    else:
        picked = review_sample(rows, n=30, seed=data.cfg.seed)
    write_review_sample(run_dir / "diffs_sample_for_review.csv", picked, cases)

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


def write_review_sample(path: Path, picked: list, cases: dict) -> None:
    """Write the review sample, keeping any review columns already filled in for the same cases."""
    entered: dict[str, dict[str, str]] = {}
    if path.exists():
        previous = pd.read_csv(path, keep_default_na=False, dtype=str)
        entered = {
            row["case_id"]: {c: row.get(c, "") for c in REVIEW_COLUMNS} for row in previous.to_dict("records")
        }
    rows = []
    for r in picked:
        review = entered.get(r.case_id, {c: "" for c in REVIEW_COLUMNS})
        rows.append({**r.to_dict(), "input": cases[r.case_id].input, **review})
    pd.DataFrame(rows, columns=SAMPLE_COLUMNS).to_csv(path, index=False)


def describe_sample(run_dir: Path, client: Any, echo: Callable[[str], None] = print) -> int:
    """Ask the judge to describe each model-only change in the review sample; returns how many were asked.

    Each answer is recorded in the run's hash chain and reused afterwards. The
    sample and the model-only diff file are then rewritten from recorded answers.
    """
    data = load_run(run_dir)
    pair = model_only_pair(data.cfg, data.arms)
    if pair is None:
        raise SystemExit("This run has no model-only pair to describe.")
    sample_path = run_dir / "diffs_sample_for_review.csv"
    if not sample_path.exists():
        raise SystemExit(f"{sample_path} not found. Run `model-diff diff` first.")
    wanted = set(pd.read_csv(sample_path, keep_default_na=False, dtype=str)["case_id"])
    _, answers = answers_for(data, load_refusals(run_dir))
    rows = [r for r in diff_answers(answers, *pair) if r.case_id in wanted]
    judge = Judge(data.cfg, client, Recorder(run_dir), run_dir / "prompts", echo)
    describe(rows, {c.case_id: c for c in data.cases}, data.tasks, judge, pair)
    diff_run(run_dir, None, echo)
    return judge.asked


def report_run(run_dir: Path, stricter_when: dict[str, str | None] | None = None,
               stricter_source: str = "the run's task file") -> Path:
    """Write report.md, per_task.md, attribution.md, and the two charts. Makes no API call.

    stricter_when maps tasks to which way is stricter; tasks missing from it fall back
    to the run's frozen task file.
    """
    data = load_run(run_dir)
    for name in ("scores.json", "diff_summary.json"):
        if not (run_dir / name).exists():
            raise SystemExit(f"{name} not found. Run `model-diff score` and `model-diff diff` first.")
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "diff_summary.json").read_text(encoding="utf-8"))
    _, answers = answers_for(data, load_refusals(run_dir))
    directions = {task: spec.stricter_when for task, spec in data.tasks.items()} | (stricter_when or {})
    reliability_path = run_dir / "judge_reliability.json"
    reliability = json.loads(reliability_path.read_text(encoding="utf-8")) if reliability_path.exists() else None
    for name, text in build(data, scores, summary, answers, run_dir, directions, stricter_source, reliability).items():
        if text:
            (run_dir / name).write_text(text, encoding="utf-8")
    return run_dir / "report.md"


def reliability_run(run_dir: Path, differ_caveat: str = "", unreliable: tuple[str, ...] = (),
                    held: tuple[str, ...] = ()) -> dict:
    """Judge-vs-human agreement on the confirmed review sample, written to judge_reliability.json.

    `unreliable` and `held` are the author's reading of which judge labels to trust; the counts must support it.
    """
    from .score import reliability as rel

    data = load_run(run_dir)
    sample = pd.read_csv(run_dir / "diffs_sample_for_review.csv", keep_default_na=False, dtype=str)
    rows = [{**r, "row": i + 1} for i, r in enumerate(sample.to_dict("records"))]
    if not all(r["human_verdict"] for r in rows):
        raise SystemExit("Some review rows have no human_verdict yet.")
    pair = model_only_pair(data.cfg, data.arms) or tuple(data.run_config["headline"])
    result = rel.agreement(rows)
    result |= {
        "pair": f"arm {pair[0]} vs arm {pair[1]}",
        "method": rel.METHOD,
        "direction_rule": rel.DIRECTION_RULE,
        "direction_readings": {task: text for task, text in rel.DIRECTION_READINGS.items() if task in data.tasks},
        "label_reading": rel.label_reading(result["per_judge_label"], list(unreliable), list(held)),
        "differ_caveat": differ_caveat,
    }
    write_json(run_dir / "judge_reliability.json", result)
    return result


# Outputs that hold only aggregates and identifiers, plus examples.md: a few hand-vetted cases quoted verbatim or
# paraphrased, written per run. No other public file carries case text or model responses.
PUBLIC_FILES = ("report.md", "per_task.md", "attribution.md", "examples.md", "accuracy_by_task.png",
                "diff_categories_by_task.png", "scores.json", "diff_summary.json", "run_config.json",
                "models_snapshot.json", "HEAD.json")


def publish_run(run_dir: Path, out_dir: Path) -> list[Path]:
    """Copy the public outputs to out_dir and write a README that anchors the run."""
    data = load_run(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in PUBLIC_FILES:
        if (run_dir / name).exists():
            shutil.copyfile(run_dir / name, out_dir / name)
            written.append(out_dir / name)
    run_id = data.run_config["run_id"]
    head = json.loads((run_dir / "HEAD.json").read_text(encoding="utf-8"))
    has_examples = (out_dir / "examples.md") in written
    scope = (
        "Apart from `examples.md`, which quotes a few vetted public cases and their model responses, these files hold"
        if has_examples else "These files hold"
    )
    readme = "\n".join([
        f"# Run {run_id}",
        "",
        f"Aggregate results of one model-diff run. {scope} no case text and no model responses; the full run",
        "directory, which quotes the public source text, stays with the author.",
        "",
        f"Chain head: `{data.head}` ({head['count']} recorded API calls).",
        "",
        "To anchor the run, compare this head with the one `verify` prints from the full run directory:",
        "",
        "```sh",
        f"uv run model-diff verify {run_id}",
        "```",
        "",
        "`verify` re-walks the SHA-256 chain over every recorded call, checks each frozen input against the hashes in",
        "`run_config.json`, and reports any edit, deletion, reordering, or truncation.",
        "",
        "Files:",
        "",
        *[f"- `{p.name}`" for p in written],
        "",
    ])
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    return [*written, out_dir / "README.md"]


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
