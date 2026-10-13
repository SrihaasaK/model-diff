"""report.md, per_task.md, attribution.md, and two charts, built offline from a verified run.

The primary comparison is the model switch alone: the step on the attribution
path that changes only the model. The headline arms (the configuration a team
gets without pinning settings) follow as a second comparison. Dollar signs are
written as \\$ so markdown previewers that render $...$ as math leave them alone.
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

from ..diff.differ import CATEGORIES, classify  # noqa: E402
from ..score.metrics import ALL_TASKS, FinalAnswer  # noqa: E402
from ..score.scoring import RunData  # noqa: E402
from .comparisons import (  # noqa: E402
    DOMINANT_SHARE,
    MIN_DIRECTIONAL,
    NO_LABEL,
    direction,
    model_only_pair,
    pair_stats,
    param_changes,
    reading,
)

# Validated categorical palette (light surface): slots 1-5 in fixed order.
SURFACE, INK, INK_SECONDARY, GRID, BAND = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#e9e8e2"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
CHANGE_CATEGORIES = [c for c in CATEGORIES if c != "same"]
Answers = dict[tuple[str, str], FinalAnswer]


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
    return "\n".join(textwrap.wrap(task.replace("_", " "), 18)) if task != ALL_TASKS else "All tasks"


def flag(m: dict) -> float | None:
    """The task's flag rate, reweighted to the source label mix where the task was sampled stratified."""
    return m["flag_rate_natural"] if m["flag_rate_natural"] is not None else m["flag_rate"]


def model_name(data: RunData, arm: str) -> str:
    snapshot = json.loads((data.run_dir / "models_snapshot.json").read_text(encoding="utf-8"))
    names = {m["id"]: m.get("display_name", m["id"]) for m in snapshot["models"]}
    model_id = data.run_config["arms"][arm]["params"]["model"]
    return names.get(model_id, model_id).removeprefix("Claude ")


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK_SECONDARY)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9)
    ax.set_axisbelow(True)


def change_counts(answers: Answers, base: str, other: str, task: str | None) -> dict[str, int]:
    """Changed cases split into label changes, cases where one side gave no label, and format-only changes."""
    counts = Counter()
    for (arm, case_id), a in answers.items():
        if arm != base or (task is not None and a.task != task):
            continue
        b = answers[(other, case_id)]
        if a.outcome != b.outcome:
            no_label = (a.outcome in NO_LABEL) != (b.outcome in NO_LABEL)
            counts["no_label" if no_label else "label"] += 1
        elif classify(a, b) == "format_drift":
            counts["format_only"] += 1
    return {"label": counts["label"], "no_label": counts["no_label"], "format_only": counts["format_only"]}


def model_only_chart(metrics: dict, base: str, other: str, names: dict[str, str], tasks: list[str], path: Path) -> None:
    """Accuracy by task for the model-only pair. The grey band is the base model's range across its repeats."""
    groups = tasks + [ALL_TASKS]
    fig, ax = plt.subplots(figsize=(9, 0.6 * len(groups) + 1.9), dpi=160, facecolor=SURFACE)
    _style(ax)
    ys = list(range(len(groups)))[::-1]
    lows = []
    for y, task in zip(ys, groups):
        mb, mo = metrics[(base, task)], metrics[(other, task)]
        band = (min(mb["repeat_accuracies"]), max(mb["repeat_accuracies"]))
        ax.fill_betweenx([y - 0.32, y + 0.32], band[0] - 0.002, band[1] + 0.002, color=BAND, zorder=1, linewidth=0)
        ax.plot([mb["accuracy"], mo["accuracy"]], [y, y], color=INK_SECONDARY, linewidth=1.2, zorder=2)
        reps = mo["repeat_accuracies"]
        ax.plot([min(reps), max(reps)], [y - 0.16, y - 0.16], color=SERIES[1], linewidth=1.2, zorder=2)
        ax.scatter([mb["accuracy"]], [y], s=64, color=SERIES[0], zorder=3, edgecolors=SURFACE, linewidths=2)
        ax.scatter([mo["accuracy"]], [y], s=64, color=SERIES[1], zorder=3, edgecolors=SURFACE, linewidths=2)
        right = max(mb["accuracy"], mo["accuracy"])
        ax.text(right + 0.012, y, f"{100 * mb['accuracy']:.1f} → {100 * mo['accuracy']:.1f} ({pts(mb['accuracy'], mo['accuracy'])})",
                va="center", fontsize=8, color=INK_SECONDARY)
        lows.append(min(band[0], min(reps), mo["accuracy"]))
    ax.set_yticks(ys, [short(t).replace("\n", " ") for t in groups])
    low = max(0.0, (int(min(lows) * 10) / 10) - 0.05)
    ax.set_xlim(low, 1.12)
    ticks = [t / 10 for t in range(int(low * 10), 11)]
    ax.set_xticks(ticks, [f"{round(100 * t)}%" for t in ticks])
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_title(f"Accuracy by task: the model switch alone ({names[base]} → {names[other]}, same effective settings)",
                 loc="left", fontsize=10.5, color=INK)
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=SERIES[0], markersize=7, label=f"{names[base]} (arm {base})"),
        plt.Line2D([], [], marker="o", linestyle="", color=SERIES[1], markersize=7, label=f"{names[other]} (arm {other})"),
        plt.Rectangle((0, 0), 1, 1, color=BAND, label=f"noise band: {names[base]}'s range across its 3 repeats"),
        plt.Line2D([], [], color=SERIES[1], linewidth=1.2, label=f"{names[other]}'s range across its 3 repeats"),
    ]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0, -0.1), ncol=2, labelcolor=INK)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def categories_chart(by_task: dict[str, dict[str, int]], notes: dict[str, dict[str, int]], totals: dict[str, int],
                     names: tuple[str, str], path: Path) -> None:
    """Stacked horizontal bars: how many cases changed, by kind of change, per task."""
    tasks = sorted(by_task) + [ALL_TASKS]
    counts = dict(by_task)
    counts[ALL_TASKS] = dict(sum((Counter(c) for c in by_task.values()), Counter()))
    fig, ax = plt.subplots(figsize=(9, 0.55 * len(tasks) + 1.8), dpi=160, facecolor=SURFACE)
    _style(ax)
    ys = list(range(len(tasks)))[::-1]
    widest = max(sum(v for k, v in c.items() if k != "same") for c in counts.values())
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
            if n >= max(3, 0.05 * widest):  # only where the number fits inside its segment
                ax.text(left + n / 2, y, str(n), ha="center", va="center", fontsize=8, color=INK)
            left += n
        note = notes[task]
        parts = [f"{note['label']} label"]
        if note["no_label"]:
            parts.append(f"{note['no_label']} no label")
        parts.append(f"{note['format_only']} format only")
        ax.text(left + widest * 0.01, y, f"{', '.join(parts)}, of {totals[task]}", va="center", fontsize=8, color=INK_SECONDARY)
    ax.set_yticks(ys, [short(t).replace("\n", " ") for t in tasks])
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_xlabel("cases", color=INK_SECONDARY, fontsize=9)
    ax.set_title(f"How {names[1]}'s final answers differ from {names[0]}'s, by task", loc="left", fontsize=11, color=INK)
    handles, labels_ = ax.get_legend_handles_labels()
    order = [labels_.index(c) for c in CHANGE_CATEGORIES if c in labels_]
    ax.legend([handles[i] for i in order], [labels_[i] for i in order], frameon=False, fontsize=8,
              loc="upper left", bbox_to_anchor=(0, -0.16), ncol=4, labelcolor=INK)
    ax.set_xlim(0, widest * 1.5 + 2)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def format_drift_split(answers: Answers, base: str, other: str) -> tuple[int, int, int]:
    """format_drift cases split into: only base broke strict format, only other did, one side unparseable."""
    base_only = other_only = unparseable = 0
    for (arm, case_id), a in answers.items():
        if arm != base or classify(a, answers[(other, case_id)]) != "format_drift":
            continue
        b = answers[(other, case_id)]
        if a.outcome != b.outcome:
            unparseable += 1
        elif not a.format_ok_majority:
            base_only += 1
        else:
            other_only += 1
    return base_only, other_only, unparseable


def violation_shapes(data: RunData, arm: str) -> Counter:
    """How an arm's responses missed the strict format: code fences, extra text, or no parseable label."""
    shapes: Counter = Counter()
    for r in data.records:
        if r.kind == "subject" and r.arm == arm and r.error is None and not r.format_ok:
            if not r.parse_ok:
                shapes["no parseable label"] += 1
            elif r.raw_response.strip().startswith("```"):
                shapes["JSON in a Markdown code fence"] += 1
            else:
                shapes["text before or after the JSON"] += 1
    return shapes


def max_token_stops(data: RunData) -> dict[str, dict]:
    """Per arm: subject calls that hit max_tokens, how many lost their label, and in which tasks."""
    out: dict[str, dict] = {}
    for r in data.records:
        if r.kind == "subject" and r.arm in data.arms and r.stop_reason == "max_tokens":
            entry = out.setdefault(r.arm, {"calls": 0, "unparsed": 0, "tasks": Counter()})
            entry["calls"] += 1
            entry["unparsed"] += not r.parse_ok
            entry["tasks"][r.task] += 1
    return out


def spend(data: RunData) -> dict:
    by: dict[str, float] = defaultdict(float)
    for r in data.records:
        cost = data.cfg.cost_usd(r.model_id, r.input_tokens, r.output_tokens, batch=r.batch_id is not None)
        label = "judge" if r.arm == "judge" else f"arm {r.arm} {r.kind.replace('_', ' ')}"
        by[label] += cost
    return dict(sorted(by.items()))


def comparison_table(base: str, other: str, metrics: dict, answers: Answers, pair: dict, names: dict[str, str], n_cases: int) -> list[str]:
    mb, mo = metrics[(base, ALL_TASKS)], metrics[(other, ALL_TASKS)]
    stats = pair_stats(answers, base, other)
    drift_base, drift_other, _ = format_drift_split(answers, base, other)
    thinking = "" if mo["mean_thinking_tokens"] is None else f"{names[other]} thinking: {mo['mean_thinking_tokens']:,.0f}"
    return [
        f"| Measure | {names[base]} (arm {base}) | {names[other]} (arm {other}) | Change |",
        "|---|---|---|---|",
        f"| Accuracy, all tasks (95% Wilson CI) | {ci(mb)} | {ci(mo)} | {pts(mb['accuracy'], mo['accuracy'])} "
        f"(exact McNemar p = {stats.mcnemar_p:.2g}; {stats.only_base_right} cases only arm {base} got right, "
        f"{stats.only_other_right} only arm {other}) |",
        f"| Final answers that changed | | | {stats.changed} of {n_cases} ({pct(stats.changed / n_cases)}): "
        f"{stats.label_changes} label changes, {stats.no_label_changes} where one side gave no parseable label |",
        f"| Same label, strict JSON compliance changed | | | {drift_base + drift_other} of {n_cases} |",
        f"| Noise floor: chance two runs of the same arm disagree | {pct(mb['noise_floor'])} | {pct(mo['noise_floor'])} | |",
        f"| Single runs of the two arms disagree | | | {pct(pair['single_run_disagreement'][ALL_TASKS])} of run pairs |",
        f"| Parse failures (per call) | {pct(mb['parse_failure_rate'], 2)} | {pct(mo['parse_failure_rate'], 2)} | "
        f"{pts(mb['parse_failure_rate'], mo['parse_failure_rate'])} |",
        f"| Not exactly the requested JSON (per call) | {pct(mb['format_violation_rate'], 2)} | "
        f"{pct(mo['format_violation_rate'], 2)} | {pts(mb['format_violation_rate'], mo['format_violation_rate'])} |",
        f"| Refusals (per call) | {pct(mb['refusal_rate'], 2)} | {pct(mo['refusal_rate'], 2)} | "
        f"{pts(mb['refusal_rate'], mo['refusal_rate'])} |",
        f"| Mean output tokens per call (thinking included) | {mb['mean_output_tokens']:,.0f} | {mo['mean_output_tokens']:,.0f} | {thinking} |",
    ]


def category_table(pair: dict, tasks: list[str]) -> list[str]:
    lines = ["| Category | " + " | ".join(f"`{t}`" for t in tasks) + " | All |", "|---|" + "---|" * (len(tasks) + 1)]
    for category in CATEGORIES:
        row = [str(pair["categories_by_task"].get(t, {}).get(category, 0)) for t in tasks]
        lines.append(f"| `{category}` | " + " | ".join(row) + f" | {pair['categories'].get(category, 0)} |")
    return lines


def per_task_rows(data: RunData, metrics: dict, answers: Answers, base: str, other: str,
                  stricter_when: dict[str, str | None]) -> list[dict]:
    rows = []
    for task in sorted(data.tasks):
        spec = data.tasks[task]
        mb, mo = metrics[(base, task)], metrics[(other, task)]
        d = direction(answers, base, other, task, set(spec.positive_labels))
        rows.append(
            {
                "task": task, "license": spec.license, "n": mb["n_cases"],
                "acc_base": mb["accuracy"], "acc_other": mo["accuracy"],
                "flag_means": ", ".join(spec.positive_labels) if len(spec.positive_labels) <= 2 else "any unfair category",
                "reweighted": mb["flag_rate_natural"] is not None,
                "flag_base": flag(mb), "flag_other": flag(mo),
                "changed": pair_stats(answers, base, other, task).changed,
                "direction": d, "reading": reading(d["call"], stricter_when.get(task)),
            }
        )
    return rows


def direction_text(row: dict) -> str:
    d = row["direction"]
    parts = [f"{d['toward']} toward the flag", f"{d['away']} away"]
    if d["lateral"]:
        parts.append(f"{d['lateral']} between non-flag or between flag labels")
    if d["no_label"]:
        parts.append(f"{d['no_label']} without a label on one side")
    return f"**{row['reading']}** ({'; '.join(parts)})"


def build_per_task(data: RunData, rows: list[dict], metrics: dict, base: str, other: str, names: dict[str, str],
                   stricter_source: str) -> str:
    b, o = names[base], names[other]
    lines = [
        f"# Per-task results: the model switch alone ({b} vs {o})",
        "",
        f"Run `{data.run_config['run_id']}`. Arm {base} ({data.run_config['arms'][base]['label']}) against arm {other} "
        f"({data.run_config['arms'][other]['label']}): identical prompts, with the model as the intended difference "
        f"(request parameters that differ: {'; '.join(param_changes(data.run_config['arms'][base]['params'], data.run_config['arms'][other]['params']))}). "
        f"Each case ran {data.run_config['n_runs']} times per arm; the final answer is the majority.",
        "",
        f"| Task | License | Cases | Accuracy {b} | Accuracy {o} | Change | Flag means | Flag rate {b} | "
        f"Flag rate {o} | Flag change | Answers changed | Direction of change |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        note = " (reweighted)" if r["reweighted"] else ""
        lines.append(
            f"| `{r['task']}` | {r['license']} | {r['n']} | {pct(r['acc_base'])} | {pct(r['acc_other'])} | "
            f"{pts(r['acc_base'], r['acc_other'])} | {r['flag_means']}{note} | {pct(r['flag_base'])} | "
            f"{pct(r['flag_other'])} | {pts(r['flag_base'], r['flag_other'])} | {r['changed']} | {direction_text(r)} |"
        )
    mb, mo = metrics[(base, ALL_TASKS)], metrics[(other, ALL_TASKS)]
    lines += [
        f"| **All tasks** | | {mb['n_cases']} | {pct(mb['accuracy'])} | {pct(mo['accuracy'])} | "
        f"{pts(mb['accuracy'], mo['accuracy'])} | | | | | {sum(r['changed'] for r in rows)} | |",
        "",
        "How to read the direction column:",
        "",
        f"- A changed answer moves *toward the flag* when {o} gives a flag label and {b} did not, and *away* in "
        "the opposite case. A task is called **more flags** or **fewer flags** when at least "
        f"{MIN_DIRECTIONAL} changes cross the flag boundary and at least {round(100 * DOMINANT_SHARE)}% of them cross it "
        "the same way. It is called **mixed** otherwise, and **too few changes to call** below that count.",
        f"- **Stricter** and **more lenient** are used only where a flag is an adverse finding ({stricter_source}): "
        "for `telemarketing_sales_rule` and `unfair_tos` more flags is stricter, and for "
        "`insurance_policy_interpretation` fewer claims judged covered is stricter. A relevance or entailment flag "
        "is not adverse, so those tasks report the raw direction.",
    ]
    for r in rows:
        if r["reweighted"]:
            mb_t, mo_t = metrics[(base, r["task"])], metrics[(other, r["task"])]
            lines.append(
                f"- `{r['task']}` was sampled with equal shares per label. Its flag rate is reweighted to the full test "
                f"split's label mix; its accuracy is over the sample as drawn (reweighted: {pct(mb_t['accuracy_natural'])} "
                f"and {pct(mo_t['accuracy_natural'])})."
            )
        if r["direction"]["no_label"]:
            lines.append(
                f"- In `{r['task']}`, {r['direction']['no_label']} changed answers are cases where one side gave no "
                "parseable label (see the output-limit note in report.md); they count as wrong for that side."
            )
    return "\n".join(lines) + "\n"


def build_attribution(data: RunData, summary: dict, metrics: dict, names: dict[str, str]) -> str:
    attribution = summary["attribution"]
    path = attribution["path"]
    arms = data.run_config["arms"]
    changed = attribution["n_changed"]
    n_cases = attribution["n_cases"]
    share = lambda n: pct(n / changed) if changed else "n/a"
    lines = [
        f"# Sequential attribution along {' → '.join(path)}",
        "",
        f"Run `{data.run_config['run_id']}`. Each arm differs from the one before it by one factor. Of the {n_cases} cases, "
        f"{changed} have a different final answer in arm {path[0]} ({arms[path[0]]['label']}) and arm {path[-1]} "
        f"({arms[path[-1]]['label']}). For each of those, the steps whose two arms give different final answers are "
        "the factors that moved it.",
        "",
        "| Arm | Configuration | Step | Request parameters changed from the previous arm | Accuracy (95% CI) | "
        "Answers changed vs previous arm | Changed answers moved by this step alone | Moved by this step with others |",
        "|---|---|---|---|---|---|---|---|",
        f"| {path[0]} | {arms[path[0]]['label']} | start | | {ci(metrics[(path[0], ALL_TASKS)])} | | | |",
    ]
    for step in attribution["steps"]:
        x, y, factor = step["from"], step["to"], step["factor"]
        diffs = "; ".join(param_changes(arms[x]["params"], arms[y]["params"]))
        moved = round(step["final_disagreement"] * n_cases)
        alone = attribution["only"][factor]
        with_others = attribution["involved"][factor] - alone
        lines.append(
            f"| {y} | {arms[y]['label']} | {factor} | {diffs} | {ci(metrics[(y, ALL_TASKS)])} | "
            f"{moved} of {n_cases} ({pct(step['final_disagreement'])}) | {alone} ({share(alone)}) | {with_others} |"
        )
    only = attribution["only"]
    ranked = sorted(only.items(), key=lambda kv: -kv[1])
    multi = changed - sum(only.values())
    lines += [
        "",
        f"**Of the {changed} answers that differ between arm {path[0]} and arm {path[-1]}, "
        + ", ".join(f"the {factor} step alone moved {n} ({share(n)})" for factor, n in ranked)
        + f"; {multi} moved at more than one step.**",
        "",
        "Combinations of steps that moved each changed answer: "
        + ", ".join(f"{k}: {v}" for k, v in attribution["combinations"].items()) + ".",
        "",
        "Notes:",
        "",
        "- This is sequential attribution along one path. Factors can interact, so changing them in a different "
        "order could split the shares differently. This order is the only one the API allows, because "
        f"{names.get(path[-1], path[-1])} cannot run at temperature 0.",
        "- A step can move an answer and a later step move it back; such cases are not among the changed answers.",
        "- The parameter column lists every request difference between consecutive arms, not only the named factor. "
        "Read it before crediting a step to its factor alone (DECISIONS.md D26 explains each difference in this run).",
        "- Run-to-run noise floors (chance two runs of the same arm disagree): "
        + ", ".join(f"{arm} {pct(metrics[(arm, ALL_TASKS)]['noise_floor'])}" for arm in path) + ".",
    ]
    return "\n".join(lines) + "\n"


def label_reading_sentences(rel: dict) -> list[str]:
    """The author's reading of which judge labels to trust, with the counts behind it."""
    reading = rel.get("label_reading") or {}
    per = rel["per_judge_label"]
    count = lambda label: f"{per[label]['agree']} of {per[label]['n']}"
    sentences = [
        f"The judge's `{label}` label matched {count(label)} reference labels and should be treated as unreliable."
        for label in reading.get("unreliable", [])
    ]
    held = reading.get("held", [])
    if held:
        named = " and ".join(f"`{label}` ({count(label)})" for label in held)
        sentence = f"{named} {'are the labels' if len(held) > 1 else 'is the label'} that held"
        # Any other label that matched every use is named too, so "held" does not read as exhaustive.
        also = [label for label, v in per.items() if label not in held and label not in reading.get("unreliable", [])
                and v["n"] and v["agree"] == v["n"]]
        if also:
            sentence += "; " + ", ".join(f"`{label}` also matched all {per[label]['n']} of its uses" for label in also)
        sentences.append(sentence + ".")
    return sentences


def judge_reliability_lines(rel: dict) -> list[str]:
    return [
        "## Judge reliability",
        "",
        f"The judge's label for the nature of each change was compared with a reference label on the {rel['n']}-case "
        f"review sample ({rel['pair']}, equal shares per change category). {rel['method']}",
        "",
        f"The judge matched the reference on **{rel['agree']} of {rel['n_reviewed']} cases "
        f"({pct(rel['agreement'])})**; on the {rel['n_judged']} cases where the judge's answer could be parsed, "
        f"{pct(rel['agreement_judged'])}. The reference differs from the judge on {rel['judge_overridden']} cases; "
        f"the author's review changed {rel['rule_overridden']} of the agent's first-pass labels."
        + "".join(f" {s}" for s in label_reading_sentences(rel)),
        "",
        "| Judge label | Cases | Matched the reference |",
        "|---|---|---|",
        *[f"| {label} | {v['n']} | {v['agree']} |" for label, v in rel["per_judge_label"].items()],
        "",
        "Disagreements (row numbers are positions in the review sample):",
        "",
        "| Row | Case | Change category | Judge | Reference | Reviewer note |",
        "|---|---|---|---|---|---|",
        *[
            f"| {d['row']} | `{d['case_id']}` | {d['category']} | {d['judge_nature']} | {d['human_verdict']} | "
            f"{d['notes']} |"
            for d in rel["disagreements"]
        ],
        "",
        "The direction rule used for the reference labels, verbatim (its row numbers are review-sample positions):",
        "",
        *[f"- {line}" for line in rel["direction_rule"]],
        "",
    ]


def build(data: RunData, scores: dict, summary: dict, answers: Answers, out_dir: Path,
          stricter_when: dict[str, str | None], stricter_source: str, reliability: dict | None = None) -> dict[str, str]:
    """Write the charts and return the text of report.md, per_task.md, and attribution.md."""
    rc = data.run_config
    head_base, head_other = summary["headline"]
    pair = model_only_pair(data.cfg, data.arms) or (head_base, head_other)
    base, other = pair
    arm_labels = {arm: a["label"] for arm, a in rc["arms"].items()}
    names = {arm: model_name(data, arm) for arm in rc["arms"]}
    metrics = {(m["arm"], m["task"]): m for m in scores["metrics"]}
    tasks = sorted(data.tasks)
    n_cases = len(data.cases)
    snapshot = json.loads((data.run_dir / "models_snapshot.json").read_text(encoding="utf-8"))
    listed = {m["id"]: m for m in snapshot["models"]}
    primary = summary["pairs"][f"{base}>{other}"]
    headline = summary["pairs"][f"{head_base}>{head_other}"]
    rows = per_task_rows(data, metrics, answers, base, other, stricter_when)
    totals = {t: sum(1 for c in data.cases if c.task == t) for t in tasks} | {ALL_TASKS: n_cases}
    truncated = max_token_stops(data)
    costs = spend(data)

    model_only_chart(metrics, base, other, names, tasks, out_dir / "accuracy_by_task.png")
    notes = {t: change_counts(answers, base, other, t) for t in tasks} | {ALL_TASKS: change_counts(answers, base, other, None)}
    categories_chart(primary["categories_by_task"], notes, totals, (names[base], names[other]), out_dir / "diff_categories_by_task.png")

    def model_line(model_id: str) -> str:
        m = listed.get(model_id, {})
        retires = f", retires {m['retires_at'][:10]}" if m.get("retires_at") else ""
        return f"`{model_id}` ({m.get('display_name', '?')}, lifecycle `{m.get('lifecycle', '?')}`{retires})"

    settings = "; ".join(param_changes(rc["arms"][base]["params"], rc["arms"][other]["params"]))
    drift_base, drift_other, drift_unparseable = format_drift_split(answers, base, other)
    shapes = {arm: violation_shapes(data, arm) for arm in (base, other)}
    lines = [
        f"# Model-change evidence: {names[base]} → {names[other]}",
        "",
        f"Run `{rc['run_id']}`, started {rc['created_at'][:16].replace('T', ' ')} UTC. {n_cases} public LegalBench cases in "
        f"{len(tasks)} compliance tasks, each sent {rc['n_runs']} times to each of {len(data.arms)} arms. Every call is "
        f"recorded in a SHA-256 hash chain; `model-diff verify {rc['run_id']}` re-checks it offline. Chain head at report "
        f"time: `{data.head}`.",
        "",
        f"Models, as reported by the models endpoint when the run started ({snapshot['retrieved_at'][:10]}): "
        f"{model_line(rc['model_a'])}, {model_line(rc['model_b'])}; judge {model_line(rc['judge_model'])}.",
        "",
        f"## Primary comparison: the model switch alone (arm {base} vs arm {other})",
        "",
        f"Arm {base} is {arm_labels[base]}; arm {other} is {arm_labels[other]}. They receive identical prompts and are the "
        "step on the attribution path whose intended difference is the model alone. Their request parameters are not "
        f"byte-identical: {settings}. Each difference expresses the same intended setting in the form each model "
        "accepts (DECISIONS.md D26).",
        "",
        *comparison_table(base, other, metrics, answers, primary, names, n_cases),
        "",
        "Per task, with flag rates and the direction of change, from `per_task.md`:",
        "",
        f"| Task | Accuracy {names[base]} | Accuracy {names[other]} | Change | Flag rate change | Answers changed | Direction |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['task']}` | {pct(r['acc_base'])} | {pct(r['acc_other'])} | {pts(r['acc_base'], r['acc_other'])} | "
            f"{pts(r['flag_base'], r['flag_other'])}{' (reweighted)' if r['reweighted'] else ''} | {r['changed']} | {r['reading']} |"
        )
    lines += [
        "",
        f"![Accuracy by task, {names[base]} vs {names[other]}, with the base model's run-to-run range as a band](accuracy_by_task.png)",
        "",
        f"### What changed between arm {base} and arm {other}",
        "",
        *category_table(primary, tasks),
        "",
        f"Of the {primary['categories'].get('format_drift', 0)} `format_drift` cases, {drift_base + drift_other} kept the same "
        f"label and changed only strict JSON compliance ({drift_base} where {names[base]}'s repeats mostly broke the format, "
        f"{drift_other} the reverse), and {drift_unparseable} are cases where one side gave no parseable label. "
        "How each arm's responses missed the requested format (per call): "
        + "; ".join(f"arm {arm}: " + (", ".join(f"{k} {v}" for k, v in shapes[arm].most_common()) or "none") for arm in (base, other))
        + ". A lenient parser reads these labels; a strict one would reject them. "
        + (
            f"The judge described {described} of this pair's changes, the cases in the human-review sample; "
            "the full set of changes was not judged."
            if (described := sum(1 for r in data.records if r.kind == "judge_diff" and (r.subject_ref or "").startswith(f"{base}>{other}|")))
            else "No judge descriptions were recorded for this pair."
        ),
        "",
        "![Diff categories by task](diff_categories_by_task.png)",
        "",
    ]
    if (head_base, head_other) != (base, other):
        hb, ho = head_base, head_other
        natures = summary["judge_natures"]
        lines += [
            f"## What a vendor sees if it does not pin settings (arm {hb} vs arm {ho})",
            "",
            f"Arm {hb} is {arm_labels[hb]}; arm {ho} is {arm_labels[ho]}: the configuration a team gets by switching the model "
            "ID and dropping the parameters the new model rejects. This mixes three changes: temperature, model, and "
            "thinking (with its larger output limit).",
            "",
            *comparison_table(hb, ho, metrics, answers, headline, names, n_cases),
            "",
            *category_table(headline, tasks),
            "",
            f"The judge ({rc['judge_model']}) described each changed case in this comparison: "
            + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(natures.items(), key=lambda kv: -kv[1]))
            + ". These are model judgements, not ground truth.",
            "",
        ]
    if summary.get("attribution"):
        attribution = summary["attribution"]
        only = attribution["only"]
        lines += [
            f"## Sequential attribution along {' → '.join(attribution['path'])}",
            "",
            f"Of the {attribution['n_changed']} answers that differ between arm {attribution['path'][0]} and arm "
            f"{attribution['path'][-1]}: "
            + ", ".join(f"the {f} step alone moved {n}" for f, n in sorted(only.items(), key=lambda kv: -kv[1]))
            + f"; {attribution['n_changed'] - sum(only.values())} moved at more than one step. This is sequential "
            "attribution along one path; factors can interact, so a different order of changes could split the shares "
            "differently. Full table, with each step's exact parameter changes, in `attribution.md`.",
            "",
        ]
    if reliability:
        lines += judge_reliability_lines(reliability)
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
    stratified = [t for t in tasks if metrics[(base, t)]["accuracy_natural"] is not None]
    for task in stratified:
        lines += [
            "",
            f"## `{task}` per-category precision and recall, arm {base} vs arm {other} (exploratory)",
            "",
            "Per-category numbers rest on about two dozen cases per label and are exploratory; the per-task tables use "
            "the pooled \"any unfair\" flag.",
            "",
            f"| Label | Support | Precision {names[base]} | Recall {names[base]} | Precision {names[other]} | Recall {names[other]} |",
            "|---|---|---|---|---|---|",
        ]
        for label, lb in metrics[(base, task)]["per_label"].items():
            lo = metrics[(other, task)]["per_label"][label]
            lines.append(f"| {label} | {lb['support']} | {pct(lb['precision'])} | {pct(lb['recall'])} | {pct(lo['precision'])} | {pct(lo['recall'])} |")
    mb, mo = metrics[(base, ALL_TASKS)], metrics[(other, ALL_TASKS)]
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
        f"4. The primary comparison is the model step (arm {base} vs arm {other}); the configuration a team gets without "
        f"pinning settings (arm {head_base} vs arm {head_other}) is reported second, and the change is attributed along "
        "the control arms.",
        "5. Each call is hash-chained to the frozen config, cases, prompts, and models snapshot.",
        *([f"6. Judge reliability: {' '.join([reliability['method'], *reliability.get('direction_readings', {}).values()])}"]
          if reliability else []),
        "",
        "## Caveats",
        "",
        f"- **Noise floor.** The primary pair runs at temperature 1.0: two runs of arm {base} disagree on "
        f"{pct(mb['noise_floor'])} of cases and two runs of arm {other} on {pct(mo['noise_floor'])}. Changes at or below "
        "these rates are not evidence of a model change. Final answers are majorities of three repeats, which reduces "
        "but does not remove that noise.",
        "- **Sampling.** Sample sizes per task: " + ", ".join(f"`{t}` {totals[t]}" for t in tasks)
        + ". The small tasks have wide intervals. `unfair_tos` is label-stratified, so its unweighted accuracy and flag "
        "rate describe the sample; reweighted figures are given. Pooled accuracy is over the sample as drawn.",
        "- **Settings.** The primary pair's request parameters differ as listed above; DECISIONS.md D26 explains why each "
        "difference is the same intended setting in the form each model accepts.",
        "- **Attribution** is sequential along one path, and interactions between factors mean another order could "
        "split the shares differently.",
        f"- **Judge.** Refusal decisions for ambiguous responses and the change descriptions come from {rc['judge_model']}, "
        "which cannot run deterministically; its answers are recorded once and reused.",
        "- **Reference labels** are LegalBench's. Some are contestable (the insurance task's labels come from crowd "
        "agreement, including an explicit \"ambiguous\" class), so accuracy measures agreement with them.",
        "- **One point in time.** Model behavior behind a pinned ID can still change; the models-list snapshot "
        "records what the API reported when the run started.",
    ]
    if truncated:
        per_arm = "; ".join(
            f"arm {arm} {e['calls']} ({', '.join(f'`{t}` {n}' for t, n in e['tasks'].most_common())}; "
            f"{e['unparsed']} without a parseable label)"
            for arm, e in sorted(truncated.items())
        )
        lines.append(
            f"- **Output limit.** Calls that stopped at their arm's `max_tokens` limit: {per_arm}. Truncated answers are "
            "reasoning written into the visible response before the JSON. Those without a label count as parse failures "
            "and as wrong answers, which understates that arm on that task."
        )
    if reliability and reliability.get("differ_caveat"):
        lines.append(f"- **Differ.** {reliability['differ_caveat']}")
    for task in stratified:
        shares = data.natural_shares()[task]
        top_label = max(shares, key=shares.get)
        sampled_top = sum(1 for c in data.cases if c.task == task and c.gold_label == top_label)
        lines.append(
            f"- **Reweighting.** The reweighted `{task}` figures give {pct(shares[top_label])} of the weight to the "
            f"{sampled_top} sampled `{top_label}` cases, so they are much less certain than the unweighted ones."
        )
    lines += ["", "## Cost", "", "| Item | Spend |", "|---|---|"]
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
    return {
        "report.md": "\n".join(lines),
        "per_task.md": build_per_task(data, rows, metrics, base, other, names, stricter_source),
        "attribution.md": build_attribution(data, summary, metrics, names) if summary.get("attribution") else "",
    }
