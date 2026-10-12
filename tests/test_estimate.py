from pathlib import Path

import pytest

from model_diff.config import load_config
from model_diff.data.cases import Case
from model_diff.estimate import ArmPlan, arm_cost, estimate, pilot_cases, probe_cases

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfg():
    return load_config(REPO / "config.yaml")


def plans(cfg, calls: int, input_per_call: int = 400) -> list[ArmPlan]:
    return [
        ArmPlan(
            arm=arm, label=a.label, model=cfg.arm_model(arm), thinking_expected=a.thinking_expected,
            max_tokens=cfg.arm_params(arm)["max_tokens"], batch_calls=calls, probe_calls=0,
            batch_input_tokens=calls * input_per_call, probe_input_tokens=0,
        )
        for arm, a in cfg.arms.items()
    ]


def test_batch_calls_are_billed_at_half_price(cfg):
    a = next(p for p in plans(cfg, 1000) if p.arm == "A")
    # Sonnet 4.5 at 3 / 15 USD per million tokens, halved for the Batch API.
    assert arm_cost(cfg, a, 100) == pytest.approx(0.5 * (400_000 * 3 + 100_000 * 15) / 1e6)


def test_every_arm_is_kept_when_the_estimate_fits(cfg):
    result = estimate(cfg, plans(cfg, 1000), n_cases=100, n_pilot_cases=5)
    assert result["status"] == "within_cap"
    assert result["dropped"] == [] and result["kept"] == ["A", "B", "C", "D"]


def test_arm_d_is_dropped_first_when_the_estimate_exceeds_the_cap(cfg):
    # Per 1,000 calls at the planning assumptions: A 1.35, B 5.90, C 1.35, D 0.90 USD.
    result = estimate(cfg, plans(cfg, 2600), n_cases=100, n_pilot_cases=5)
    assert result["total_expected_usd_all_arms"] > cfg.cost_cap_usd
    assert result["dropped"] == ["D"]
    assert result["status"] == "within_cap_after_dropping"
    assert result["total_expected_usd"] <= cfg.cost_cap_usd


def test_still_over_after_dropping_means_the_run_does_not_start(cfg):
    result = estimate(cfg, plans(cfg, 3000), n_cases=100, n_pilot_cases=5)
    assert result["dropped"] == ["D"]
    assert result["status"] == "over_cap"


def test_break_even_thinking_length_reproduces_the_cap(cfg):
    result = estimate(cfg, plans(cfg, 2000), n_cases=100, n_pilot_cases=5)
    tokens = result["break_even_thinking_tokens"]["all_arms"]
    at_break_even = cfg.model_copy(update={"run": cfg.run.model_copy(update={"planning_thinking_tokens": round(tokens)})})
    total = estimate(at_break_even, plans(cfg, 2000), 100, 5)["total_expected_usd_all_arms"]
    assert total == pytest.approx(cfg.cost_cap_usd, abs=0.02)


def test_probe_and_pilot_cases_are_deterministic_per_task():
    cases = [Case(case_id=f"{t}-{i:03d}", task=t, input="x", gold_label="Yes", license="MIT") for t in "ab" for i in range(40)]
    probes = probe_cases(cases, 10)
    assert [c.case_id for c in probes] == [f"{t}-{i:03d}" for t in "ab" for i in range(10)]
    pilot = pilot_cases(list(reversed(cases)), 0.05, 42)
    assert pilot == pilot_cases(cases, 0.05, 42)
    assert [c.task for c in pilot] == ["a", "a", "b", "b"]
