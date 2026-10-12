"""report.md and its two charts, built offline from a verified run directory.

Dollar signs are written as \\$ so markdown previewers that render $...$ as
math leave the cost figures alone.
"""

from __future__ import annotations

import json
import textwrap
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from ..diff.differ import CATEGORIES  # noqa: E402
from ..score.metrics import ALL_TASKS, FinalAnswer  # noqa: E402
from ..score.scoring import RunData  # noqa: E402
from ..score.stats import mcnemar_exact  # noqa: E402

# Validated categorical palette (light surface): slots 1-5 in fixed order.
SURFACE, INK, INK_SECONDARY, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
CHANGE_CATEGORIES = [c for c in CATEGORIES if c != "same"]


def pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f}%"


def pts(a: float | None, b: float | None) -> str:
    if a is None or b is None:
        return "n/a"
    return f"{100 * (b - a):+.1f} pts"


def usd(x: float) -> str:
    return f"\\${x:,.2f}"


def ci(m: dict) -> str:
    lo, hi = m["accuracy_ci95"]
    return f"{pct(m['accuracy'])} ({pct(lo)}–{pct(hi)})"


def short(task: str) -> str:
    return "\n".join(textwrap.wrap(task.replace("_", " "), 16)) if task != ALL_TASKS else "All tasks"


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK_SECONDARY)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9)
    ax.set_axisbelow(True)


def accuracy_chart(metrics: dict, arms: tuple[str, str], labels: dict[str, str], tasks: list[str], path: Path) -> None:
    """Grouped bars of accuracy by task for the headline arms; whiskers span single-repeat accuracy."""
    groups = tasks + [ALL_TASKS]
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160, facecolor=SURFACE)
    _style(ax)
    width = 0.36
    for i, arm in enumerate(arms):
        xs = [g + (i - 0.5) * (width + 0.03) for g in range(len(groups))]
        values = [metrics[(arm, t)]["accuracy"] for t in groups]
        ax.bar(xs, values, width=width, color=SERIES[i], label=f"{arm}: {labels[arm]}", zorder=2)
        for x, task, value in zip(xs, groups, values):
            reps = metrics[(arm, task)]["repeat_accuracies"]
            low, high = min(reps), max(reps)
            ax.plot([x, x], [low, high], color=INK, linewidth=1.2, zorder=3)
            for end in (low, high):
                ax.plot([x - 0.06, x + 0.06], [end, end], color=INK, linewidth=1.2, zorder=3)
            ax.text(x, max(value, high) + 0.015, f"{100 * value:.0f}", ha="center", va="bottom", fontsize=8, color=INK_SECONDARY)
    ax.set_xticks(range(len(groups)), [short(t) for t in groups])
    ax.set_ylim(0, 1.08)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_title("Accuracy by task (final answer = majority of 3 repeats)", loc="left", fontsize=11, color=INK)
    ax.text(0, -0.24, "Whiskers: lowest to highest accuracy of a single repeat scored alone (the noise floor).",
            transform=ax.transAxes, fontsize=8, color=INK_SECONDARY)
    ax.legend(frameon=False, fontsize=9, loc="upper left", bbox_to_anchor=(0, -0.28), ncol=2, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def categories_chart(by_task: dict[str, dict[str, int]], totals: dict[str, int], path: Path) -> None:
    """Stacked horizontal bars: how many cases changed, by kind of change, per task."""
    tasks = sorted(by_task) + [ALL_TASKS]
    counts = dict(by_task)
    counts[ALL_TASKS] = dict(sum((Counter(c) for c in by_task.values()), Counter()))
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(tasks) + 1.8), dpi=160, facecolor=SURFACE)
    _style(ax)
    ys = list(range(len(tasks)))[::-1]
    labelled: set[str] = set()
    for y, task in zip(ys, tasks):
        left = 0
        for i, category in enumerate(CHANGE_CATEGORIES):
            n = counts[task].get(category, 0)
            if not n:
                continue
            label = category if category not in labelled else None
            labelled.add(category)
            ax.barh(y, n, left=left, color=SERIES[i], height=0.6, edgecolor=SURFACE, linewidth=2, zorder=2, label=label)
            if n >= 3:
                ax.text(left + n / 2, y, str(n), ha="center", va="center", fontsize=8, color=INK)
            left += n
        ax.text(left + 0.5, y, f"{left} of {totals[task]} changed", va="center", fontsize=8, color=INK_SECONDARY)
    ax.set_yticks(ys, [short(t).replace("\n", " ") for t in tasks])
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_xlabel("cases", color=INK_SECONDARY, fontsize=9)
    ax.set_title("How model B's final answers differ from model A's, by task", loc="left", fontsize=11, color=INK)
    handles, names = ax.get_legend_handles_labels()
    order = [names.index(c) for c in CHANGE_CATEGORIES if c in names]
    ax.legend([handles[i] for i in order], [names[i] for i in order], frameon=False, fontsize=8,
              loc="upper left", bbox_to_anchor=(0, -0.12 - 0.02 * len(tasks)), ncol=3, labelcolor=INK)
    widest = max(sum(v for k, v in c.items() if k != "same") for c in counts.values())
    ax.set_xlim(0, widest * 1.35 + 2)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def spend(data: RunData) -> dict:
    by: dict[str, float] = defaultdict(float)
    for r in data.records:
        cost = data.cfg.cost_usd(r.model_id, r.input_tokens, r.output_tokens, batch=r.batch_id is not None)
        label = "judge" if r.arm == "judge" else f"arm {r.arm} {r.kind.replace('_', ' ')}"
        by[label] += cost
    return dict(sorted(by.items()))


def build(data: RunData, scores: dict, summary: dict, answers: dict[tuple[str, str], FinalAnswer], out_dir: Path) -> str:
    rc = data.run_config
    base, other = summary["headline"]
    arm_labels = {arm: a["label"] for arm, a in rc["arms"].items()}
    metrics = {(m["arm"], m["task"]): m for m in scores["metrics"]}
    tasks = sorted(data.tasks)
    a_all, b_all = metrics[(base, ALL_TASKS)], metrics[(other, ALL_TASKS)]
    headline = summary["pairs"][f"{base}>{other}"]
    only_a = sum(1 for (arm, c), x in answers.items() if arm == base and x.correct and not answers[(other, c)].correct)
    only_b = sum(1 for (arm, c), x in answers.items() if arm == base and not x.correct and answers[(other, c)].correct)
    p_value = mcnemar_exact(only_a, only_b)
    snapshot = json.loads((data.run_dir / "models_snapshot.json").read_text(encoding="utf-8"))
    listed = {m["id"]: m for m in snapshot["models"]}
    costs = spend(data)
    n_cases = len(data.cases)
    changed_cases = round(headline["final_disagreement"][ALL_TASKS] * n_cases)
    thinking_note = "" if b_all["mean_thinking_tokens"] is None else f"{other} thinking: {b_all['mean_thinking_tokens']:,.0f}"

    accuracy_chart(metrics, (base, other), arm_labels, tasks, out_dir / "accuracy_by_task.png")
    totals = {t: sum(1 for c in data.cases if c.task == t) for t in tasks} | {ALL_TASKS: n_cases}
    categories_chart(headline["categories_by_task"], totals, out_dir / "diff_categories_by_task.png")

    def model_line(model_id: str) -> str:
        m = listed.get(model_id, {})
        retires = f", retires {m['retires_at'][:10]}" if m.get("retires_at") else ""
        return f"`{model_id}` ({m.get('display_name', '?')}, lifecycle `{m.get('lifecycle', '?')}`{retires})"

    lines = [
        f"# Model-change evidence: {arm_labels[base]} vs {arm_labels[other]}",
        "",
        f"Run `{rc['run_id']}`, started {rc['created_at'][:16].replace('T', ' ')} UTC. {n_cases} public LegalBench cases in "
        f"{len(tasks)} compliance tasks, each sent {rc['n_runs']} times to each arm. Every call is recorded in a "
        f"SHA-256 hash chain; `model-diff verify {rc['run_id']}` re-checks it offline. Chain head at report time: "
        f"`{data.head}`.",
        "",
        f"Models, as reported by the models endpoint when the run started ({snapshot['retrieved_at'][:10]}): "
        f"{model_line(rc['model_a'])}, {model_line(rc['model_b'])}; judge {model_line(rc['judge_model'])}.",
        "",
        f"## Headline: arm {base} vs arm {other}",
        "",
        f"Arm {base} is {arm_labels[base]}; arm {other} is {arm_labels[other]}, the configuration a team gets by switching "
        "the model ID and dropping the parameters the new model rejects.",
        "",
        f"| Measure | {base} | {other} | Change |",
        "|---|---|---|---|",
        f"| Accuracy, all tasks (95% Wilson CI) | {ci(a_all)} | {ci(b_all)} | {pts(a_all['accuracy'], b_all['accuracy'])} "
        f"(exact McNemar p = {p_value:.3g}; {only_a} cases only {base} got right, {only_b} only {other}) |",
        f"| Cases whose final answer changed | | | {changed_cases} of {n_cases} ({pct(headline['final_disagreement'][ALL_TASKS])}) |",
        f"| Noise floor: chance two runs of the same arm disagree | {pct(a_all['noise_floor'])} | {pct(b_all['noise_floor'])} | |",
        f"| Single runs of {base} and {other} disagree | | | {pct(headline['single_run_disagreement'][ALL_TASKS])} of run pairs |",
        f"| Parse failures (per call) | {pct(a_all['parse_failure_rate'], 2)} | {pct(b_all['parse_failure_rate'], 2)} | "
        f"{pts(a_all['parse_failure_rate'], b_all['parse_failure_rate'])} |",
        f"| Not exactly the requested JSON (per call) | {pct(a_all['format_violation_rate'], 2)} | "
        f"{pct(b_all['format_violation_rate'], 2)} | {pts(a_all['format_violation_rate'], b_all['format_violation_rate'])} |",
        f"| Refusals (per call) | {pct(a_all['refusal_rate'], 2)} | {pct(b_all['refusal_rate'], 2)} | "
        f"{pts(a_all['refusal_rate'], b_all['refusal_rate'])} |",
        f"| Mean latency, sequential probes | {a_all['mean_latency_ms'] or 0:,.0f} ms | {b_all['mean_latency_ms'] or 0:,.0f} ms | "
        f"{a_all['latency_samples']} and {b_all['latency_samples']} calls |",
        f"| Mean output tokens per call (thinking included) | {a_all['mean_output_tokens']:,.0f} | "
        f"{b_all['mean_output_tokens']:,.0f} | {thinking_note} |",
        "",
        "Flag rate is the share of cases whose final answer is the task's affirmative label. For `unfair_tos` the flag is "
        "\"any potentially unfair category\", reweighted from the label-stratified sample to the full test split's mix.",
        "",
        f"| Task | Flag means | {base} | {other} | Change |",
        "|---|---|---|---|---|",
    ]
    for task in tasks:
        spec = data.tasks[task]
        flag = ", ".join(spec.positive_labels) if len(spec.positive_labels) <= 2 else "any unfair category"
        a_m, b_m = metrics[(base, task)], metrics[(other, task)]
        natural = a_m["flag_rate_natural"] is not None
        a_flag = a_m["flag_rate_natural"] if natural else a_m["flag_rate"]
        b_flag = b_m["flag_rate_natural"] if natural else b_m["flag_rate"]
        note = " (reweighted)" if natural else ""
        lines.append(f"| `{task}` | {flag}{note} | {pct(a_flag)} | {pct(b_flag)} | {pts(a_flag, b_flag)} |")

    lines += [
        "",
        "## Per-task results",
        "",
        f"| Task | Cases | Accuracy {base} | Accuracy {other} | Change | Noise floor {base} / {other} | "
        f"Parse fail {base} / {other} | Refusal {base} / {other} | Latency {base} / {other} |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for task in tasks + [ALL_TASKS]:
        a_m, b_m = metrics[(base, task)], metrics[(other, task)]
        lat = lambda m: "n/a" if m["mean_latency_ms"] is None else f"{m['mean_latency_ms']:,.0f} ms"
        name = "**All tasks**" if task == ALL_TASKS else f"`{task}`"
        lines.append(
            f"| {name} | {a_m['n_cases']} | {ci(a_m)} | {ci(b_m)} | {pts(a_m['accuracy'], b_m['accuracy'])} | "
            f"{pct(a_m['noise_floor'])} / {pct(b_m['noise_floor'])} | {pct(a_m['parse_failure_rate'], 2)} / "
            f"{pct(b_m['parse_failure_rate'], 2)} | {pct(a_m['refusal_rate'], 2)} / {pct(b_m['refusal_rate'], 2)} | "
            f"{lat(a_m)} / {lat(b_m)} |"
        )
    stratified = [t for t in tasks if metrics[(base, t)]["accuracy_natural"] is not None]
    for task in stratified:
        a_m, b_m = metrics[(base, task)], metrics[(other, task)]
        lines += [
            "",
            f"`{task}` was sampled with equal shares per label. Reweighted to the full test split's label mix, accuracy is "
            f"{pct(a_m['accuracy_natural'])} for {base} and {pct(b_m['accuracy_natural'])} for {other}.",
        ]
    lines += [
        "",
        "![Accuracy by task, arm A vs arm B, with the range of single-repeat accuracy](accuracy_by_task.png)",
        "",
        f"## What changed between {base} and {other}",
        "",
        "Each case is classified by comparing the two arms' final answers: `same`; `A_right_B_wrong` and `A_wrong_B_right` "
        "(the answer changed and exactly one matches the reference label); `both_wrong_differently`; `format_drift` (one "
        "side's answer could not be parsed, or the label held but strict JSON compliance changed); `refusal_change`.",
        "",
        "| Category | " + " | ".join(f"`{t}`" for t in tasks) + " | All |",
        "|---|" + "---|" * (len(tasks) + 1),
    ]
    by_task = headline["categories_by_task"]
    for category in CATEGORIES:
        row = [str(by_task.get(t, {}).get(category, 0)) for t in tasks]
        lines.append(f"| `{category}` | " + " | ".join(row) + f" | {headline['categories'].get(category, 0)} |")
    natures = summary["judge_natures"]
    if natures:
        lines += [
            "",
            f"The judge ({rc['judge_model']}) described each changed case. Natures of change: "
            + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(natures.items(), key=lambda kv: -kv[1]))
            + ". These are model judgements, not ground truth; `diffs_sample_for_review.csv` holds a 30-case stratified "
            "sample with blank `human_verdict` and `notes` columns for checking them.",
        ]
    lines += ["", "![Diff categories by task](diff_categories_by_task.png)", ""]

    attribution = summary.get("attribution")
    if attribution:
        path = " → ".join(attribution["path"])
        changed = attribution["n_changed"]
        lines += [
            f"## Sequential attribution along the path {path}",
            "",
            "Each step changes one factor. For every case whose final answer differs between the first and last arm, the "
            "steps whose two arms give different final answers are the factors that moved it. **This is sequential "
            "attribution along one path.** Factors can interact, so a different order of changes could split the shares "
            "differently. The order here is the only one the API allows, because Sonnet 5.5 cannot run at temperature 0.",
            "",
            "| Step | Factor | Final answers differ | Single runs differ | Noise floors of the two arms |",
            "|---|---|---|---|---|",
        ]
        for step in attribution["steps"]:
            nf = f"{pct(metrics[(step['from'], ALL_TASKS)]['noise_floor'])} / {pct(metrics[(step['to'], ALL_TASKS)]['noise_floor'])}"
            lines.append(
                f"| {step['from']} → {step['to']} | {step['factor']} | {pct(step['final_disagreement'])} | "
                f"{pct(step['single_run_disagreement'])} | {nf} |"
            )
        share = lambda n: pct(n / changed) if changed else "n/a"
        lines += [
            "",
            f"Of the {changed} cases whose final answer differs between {attribution['path'][0]} and {attribution['path'][-1]}:",
            "",
            "| Factor | Moved the answer alone | Involved (alone or with others) |",
            "|---|---|---|",
        ]
        for factor in attribution["only"]:
            lines.append(
                f"| {factor} | {attribution['only'][factor]} ({share(attribution['only'][factor])}) | "
                f"{attribution['involved'][factor]} ({share(attribution['involved'][factor])}) |"
            )
        combos = ", ".join(f"{k or 'none'}: {v}" for k, v in attribution["combinations"].items())
        lines += [
            "",
            f"Combinations of steps that moved each changed case: {combos}. A step can also move an answer and a later "
            "step move it back; such cases are not in this count.",
            "",
        ]

    lines += [
        "## All arms",
        "",
        "| Arm | Configuration | Accuracy (95% CI) | Noise floor | Unanimous cases | Parse fail | Refusal | "
        "Mean output tokens | Mean thinking tokens |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in data.arms:
        m = metrics[(arm, ALL_TASKS)]
        thinking = "n/a" if m["mean_thinking_tokens"] is None else f"{m['mean_thinking_tokens']:,.0f}"
        lines.append(
            f"| {arm} | {arm_labels[arm]} | {ci(m)} | {pct(m['noise_floor'])} | {pct(m['unanimity_rate'])} | "
            f"{pct(m['parse_failure_rate'], 2)} | {pct(m['refusal_rate'], 2)} | {m['mean_output_tokens']:,.0f} | {thinking} |"
        )
    dropped = data.state.get("dropped_arms", [])
    if dropped:
        lines += ["", f"Arm(s) {', '.join(dropped)} were dropped after the pilot to fit the cost cap; their pilot calls "
                  "are recorded but not scored."]

    for task in stratified:
        lines += [
            "",
            f"## `{task}` per-category precision and recall (exploratory)",
            "",
            "Per-category numbers rest on about two dozen cases per label and are exploratory; the headline uses the "
            "pooled \"any unfair\" flag above.",
            "",
            f"| Label | Support | Precision {base} | Recall {base} | Precision {other} | Recall {other} |",
            "|---|---|---|---|---|---|",
        ]
        for label, a_l in metrics[(base, task)]["per_label"].items():
            b_l = metrics[(other, task)]["per_label"][label]
            lines.append(
                f"| {label} | {a_l['support']} | {pct(a_l['precision'])} | {pct(a_l['recall'])} | "
                f"{pct(b_l['precision'])} | {pct(b_l['recall'])} |"
            )

    sampled = {t: totals[t] for t in tasks}
    lines += [
        "",
        "## Method",
        "",
        f"1. {n_cases} cases from {len(tasks)} LegalBench test splits (commit `{data.cfg.corpus.revision[:12]}`), drawn with "
        f"seed {rc['seed']}; `unfair_tos` is label-stratified, the others random or whole.",
        f"2. Every case went {rc['n_runs']} times to each arm through the Message Batches API with byte-identical prompts; "
        "arms differ only in the parameters stored with every record.",
        "3. Responses are parsed as JSON; an arm's final answer is the majority of its repeats; refusals come from the "
        "API's stop reason, a rule set, and the judge.",
        f"4. Final answers of arms {base} and {other} are compared case by case, the judge describes each change, and "
        "the change is attributed to temperature, model, and thinking along the control arms.",
        "5. Each call is hash-chained to the frozen config, cases, prompts, and models snapshot; latency comes from "
        "separate sequential calls, since batch results carry none.",
        "",
        "## Caveats",
        "",
        f"- **Noise floor.** Arm {other} cannot run at temperature 0 (the API rejects it), so it carries sampling noise "
        f"that arm {base} does not: two runs of {other} disagree on {pct(b_all['noise_floor'])} of cases, against "
        f"{pct(a_all['noise_floor'])} for {base}. Changes at or below these rates are not evidence of a model change. "
        "Final answers are majorities of three repeats, which reduces but does not remove that noise.",
        "- **Sampling.** Sample sizes per task: " + ", ".join(f"`{t}` {n}" for t, n in sampled.items())
        + ". The small tasks have wide intervals. `unfair_tos` is label-stratified, so its unweighted accuracy and "
        "flag rate describe the sample; reweighted figures are given. Pooled accuracy is over the sample as drawn.",
        "- **Attribution** is sequential along one path, and interactions between factors mean another order could "
        "split the shares differently.",
        f"- **Judge.** Refusal decisions for ambiguous responses and every change description come from {rc['judge_model']}, "
        "which cannot run deterministically. Its answers are recorded once and reused, and a human review sample is provided.",
        "- **Reference labels** are LegalBench's. Some are contestable (the insurance task's labels come from crowd "
        "agreement, including an explicit \"ambiguous\" class), so accuracy measures agreement with them.",
        "- **One point in time.** Model behaviour behind a pinned ID can still change; the models-list snapshot "
        "records what the API reported when the run started.",
        f"- **Latency** comes from {a_all['latency_samples']} sequential calls per arm plus any direct fallback calls, "
        "not from the batch, and depends on load at the time.",
        "",
        "## Cost",
        "",
        "| Item | Spend |",
        "|---|---|",
    ]
    for item, cost in costs.items():
        lines.append(f"| {item} | {usd(cost)} |")
    projection = data.state.get("projection", {})
    lines += [
        f"| **Total** | **{usd(sum(costs.values()))}** |",
        "",
        f"Cost cap {usd(rc['cost_cap_usd'])}. After the pilot, the run projected {usd(projection.get('projected_total_usd', 0))} "
        f"from measured usage and kept arms {', '.join(data.state.get('kept_arms', []))}. Prices: Anthropic list prices "
        "on 2026-10-12, with the Batch API at half price.",
        "",
        "## Reproduce and verify",
        "",
        "```sh",
        f"uv run model-diff verify {rc['run_id']}   # offline: re-walks the hash chain and frozen artifacts",
        f"uv run model-diff report {rc['run_id']}   # offline: rebuilds this report from the run directory",
        "```",
        "",
        "## Data and licenses",
        "",
        "Cases are from LegalBench (Guha et al., 2023). Task licenses: "
        + "; ".join(f"`{t}` {data.tasks[t].license}" for t in tasks)
        + ". Source datasets should be cited as their LegalBench task cards ask.",
        "",
    ]
    return "\n".join(lines)
