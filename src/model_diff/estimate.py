"""Dry run: price the run before any paid call.

Input tokens are exact: every distinct prompt is counted with the free
token-counting endpoint, for the model that will receive it. Output tokens
cannot be known in advance, so the estimate uses a planning assumption for the
visible answer and, for arms that think, for thinking tokens, and shows how the
total moves with thinking length. The run starts with a pilot batch whose
measured usage replaces these assumptions before the rest is submitted.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import anthropic

from .api import with_backoff
from .config import Config
from .data.cases import Case
from .prompts import PromptBook

PREFLIGHT_TOKENS = 200  # generous per-call bound for the tiny parameter-check request


def probe_cases(cases: list[Case], per_task: int) -> list[Case]:
    """The first per_task cases of each task by case_id; these get sequential latency calls."""
    by_task: dict[str, list[Case]] = defaultdict(list)
    for case in sorted(cases, key=lambda c: c.case_id):
        by_task[case.task].append(case)
    return [c for task in sorted(by_task) for c in by_task[task][:per_task]]


def pilot_cases(cases: list[Case], fraction: float, seed: int) -> list[Case]:
    """A seeded share of each task's cases, run first so measured usage can re-project the cost."""
    by_task: dict[str, list[Case]] = defaultdict(list)
    for case in sorted(cases, key=lambda c: c.case_id):
        by_task[case.task].append(case)
    picked = []
    for task in sorted(by_task):
        k = max(1, math.ceil(fraction * len(by_task[task])))
        picked += random.Random(f"{seed}:pilot:{task}").sample(by_task[task], k)
    return sorted(picked, key=lambda c: (c.task, c.case_id))


def count_input_tokens(
    client: anthropic.Anthropic,
    cfg: Config,
    book: PromptBook,
    cases: list[Case],
    cache_path: Path,
    echo: Callable[[str], None] = print,
    workers: int = 8,
) -> dict[tuple[str, str], int]:
    """Input tokens for every (model, prompt) pair, from the free count_tokens endpoint, cached on disk."""
    needed: dict[tuple[str, str], dict] = {}
    for model in sorted({cfg.arm_model(arm) for arm in cfg.arms}):
        for case in cases:
            request, sha = book.request(case, {})
            needed[(model, sha)] = request

    counts: dict[tuple[str, str], int] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            counts[(row["model"], row["prompt_sha256"])] = row["input_tokens"]
    todo = [key for key in needed if key not in counts]
    echo(f"Counting input tokens: {len(needed)} distinct (model, prompt) pairs, {len(todo)} not cached.")

    def count(key: tuple[str, str]) -> tuple[tuple[str, str], int]:
        request = needed[key]
        response = with_backoff(
            lambda: client.messages.count_tokens(model=key[0], system=request["system"], messages=request["messages"])
        )
        return key, response.input_tokens

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=workers) as pool, cache_path.open("a", encoding="utf-8") as cache:
        for i, (key, tokens) in enumerate(pool.map(count, todo), start=1):
            counts[key] = tokens
            cache.write(json.dumps({"model": key[0], "prompt_sha256": key[1], "input_tokens": tokens}) + "\n")
            if i % 250 == 0:
                echo(f"  counted {i}/{len(todo)}")
    return {key: counts[key] for key in needed}


@dataclass
class ArmPlan:
    arm: str
    label: str
    model: str
    thinking_expected: bool
    max_tokens: int
    batch_calls: int
    probe_calls: int
    batch_input_tokens: int
    probe_input_tokens: int


def plan_arms(cfg: Config, book: PromptBook, cases: list[Case], counts: dict[tuple[str, str], int]) -> list[ArmPlan]:
    probes = probe_cases(cases, cfg.run.latency_probe_cases)
    plans = []
    for arm, arm_cfg in cfg.arms.items():
        model = cfg.arm_model(arm)
        tokens = {case.case_id: counts[(model, book.request(case, {})[1])] for case in cases}
        plans.append(
            ArmPlan(
                arm=arm,
                label=arm_cfg.label,
                model=model,
                thinking_expected=arm_cfg.thinking_expected,
                max_tokens=cfg.arm_params(arm)["max_tokens"],
                batch_calls=len(cases) * cfg.n_runs,
                probe_calls=len(probes),
                batch_input_tokens=sum(tokens.values()) * cfg.n_runs,
                probe_input_tokens=sum(tokens[c.case_id] for c in probes),
            )
        )
    return plans


def output_per_call(cfg: Config, plan: ArmPlan, thinking_tokens: int) -> int:
    return cfg.run.expected_output_tokens + (thinking_tokens if plan.thinking_expected else 0)


def arm_cost(cfg: Config, plan: ArmPlan, out_per_call: float) -> float:
    batch = cfg.cost_usd(plan.model, plan.batch_input_tokens, plan.batch_calls * out_per_call, batch=True)
    probe = cfg.cost_usd(plan.model, plan.probe_input_tokens, plan.probe_calls * out_per_call, batch=False)
    return batch + probe


def estimate(cfg: Config, plans: list[ArmPlan], n_cases: int, n_pilot_cases: int) -> dict:
    """Expected cost, the cap decision with the configured drop order, and thinking sensitivity."""
    by_arm = {p.arm: p for p in plans}
    preflight = sum(cfg.cost_usd(p.model, PREFLIGHT_TOKENS, PREFLIGHT_TOKENS, batch=False) for p in plans)
    fixed = preflight + cfg.judge.budget_usd

    def total(arms: list[str], thinking: int) -> float:
        return fixed + sum(arm_cost(cfg, by_arm[a], output_per_call(cfg, by_arm[a], thinking)) for a in arms)

    def break_even(arms: list[str]) -> float | None:
        """Mean thinking tokens per call at which the total reaches the cap."""
        base, slope = total(arms, 0), total(arms, 1) - total(arms, 0)
        return (cfg.cost_cap_usd - base) / slope if slope > 0 else None

    planning = cfg.run.planning_thinking_tokens
    kept = list(by_arm)
    dropped = []
    for arm in cfg.drop_order:
        if total(kept, planning) <= cfg.cost_cap_usd:
            break
        kept.remove(arm)
        dropped.append(arm)
    within = total(kept, planning) <= cfg.cost_cap_usd
    status = "within_cap" if within and not dropped else "within_cap_after_dropping" if within else "over_cap"

    arms = []
    for p in plans:
        out = output_per_call(cfg, p, planning)
        arms.append(
            {
                **asdict(p),
                "output_per_call": out,
                "expected_usd": arm_cost(cfg, p, out),
                # Every call hitting max_tokens; not meaningful when thinking can use most of a large budget.
                "upper_usd": None if p.thinking_expected else arm_cost(cfg, p, p.max_tokens),
                "kept": p.arm in kept,
            }
        )
    all_arms = list(by_arm)
    return {
        "cap_usd": cfg.cost_cap_usd,
        "planning": {
            "expected_output_tokens": cfg.run.expected_output_tokens,
            "thinking_tokens": planning,
        },
        "arms": arms,
        "preflight_usd": preflight,
        "judge_budget_usd": cfg.judge.budget_usd,
        "total_expected_usd_all_arms": total(all_arms, planning),
        "total_expected_usd": total(kept, planning),
        "kept": kept,
        "dropped": dropped,
        "status": status,
        "scenarios": [
            {"thinking_tokens": t, "all_arms_usd": total(all_arms, t), "kept_arms_usd": total(kept, t)}
            for t in cfg.run.thinking_scenarios
        ],
        "break_even_thinking_tokens": {"all_arms": break_even(all_arms), "kept_arms": break_even(kept)},
        "pilot": {
            "cases": n_pilot_cases,
            "of_cases": n_cases,
            "expected_usd": sum(
                arm_cost(cfg, by_arm[a], output_per_call(cfg, by_arm[a], planning)) * n_pilot_cases / n_cases
                for a in kept
            ),
        },
    }


def render(result: dict) -> str:
    usd = lambda x: "n/a" if x is None else f"${x:,.2f}"
    lines = [
        f"{'arm':<4} {'label':<28} {'model':<28} {'calls':>6} {'input tok':>10} {'out/call':>8} {'expected':>9} {'all-max':>9}",
    ]
    for a in result["arms"]:
        calls = a["batch_calls"] + a["probe_calls"]
        tokens = a["batch_input_tokens"] + a["probe_input_tokens"]
        mark = "" if a["kept"] else "  (dropped)"
        lines.append(
            f"{a['arm']:<4} {a['label'][:28]:<28} {a['model']:<28} {calls:>6} {tokens:>10,} {a['output_per_call']:>8} "
            f"{usd(a['expected_usd']):>9} {usd(a['upper_usd']):>9}{mark}"
        )
    planning = result["planning"]
    lines += [
        "",
        f"Planning assumptions: {planning['expected_output_tokens']} visible output tokens per call; "
        f"{planning['thinking_tokens']} thinking tokens per call for arms that think by default.",
        f"Preflight checks {usd(result['preflight_usd'])}; judge budget (hard ceiling) {usd(result['judge_budget_usd'])}.",
        f"Expected total, all arms: {usd(result['total_expected_usd_all_arms'])}",
        f"Expected total, arms kept ({', '.join(result['kept'])}): {usd(result['total_expected_usd'])}"
        f" against a cap of {usd(result['cap_usd'])}",
        "",
        "Sensitivity to thinking length (the main unknown):",
    ]
    for s in result["scenarios"]:
        lines.append(f"  {s['thinking_tokens']:>5} thinking tokens/call: all arms {usd(s['all_arms_usd'])}, kept arms {usd(s['kept_arms_usd'])}")
    be = result["break_even_thinking_tokens"]
    lines.append(
        "Cap is reached at about "
        + (f"{be['all_arms']:,.0f}" if be["all_arms"] is not None else "n/a")
        + " thinking tokens/call with all arms"
        + (f", {be['kept_arms']:,.0f} with the kept arms." if be["kept_arms"] is not None else ".")
    )
    pilot = result["pilot"]
    lines += [
        f"Pilot: {pilot['cases']} of {pilot['of_cases']} cases run first (expected {usd(pilot['expected_usd'])}); "
        "their measured usage re-projects the total before the rest is submitted.",
        "",
        {
            "within_cap": "Decision: WITHIN CAP with every arm.",
            "within_cap_after_dropping": f"Decision: WITHIN CAP after dropping arm(s) {', '.join(result['dropped'])}.",
            "over_cap": "Decision: OVER CAP even after dropping every droppable arm. The run will not start.",
        }[result["status"]],
    ]
    return "\n".join(lines)
