import pytest

from model_diff.score.metrics import (
    ALL_TASKS,
    PARSE_FAIL,
    REFUSAL,
    compute_metrics,
    final_answers,
    latency_samples,
    majority_vote,
    observations_from_records,
)
from model_diff.score.parse import parse_response
from model_diff.score.stats import mcnemar_exact, wilson_interval


@pytest.fixture
def metrics(records, gold, labels, positive):
    observations = observations_from_records(records, refusals={})
    answers = final_answers(observations, gold)
    results = compute_metrics(answers, observations, latency_samples(records), labels, positive)
    return {(m.role, m.task): m for m in results}


def test_fixture_parse_fields_match_the_parser(records, labels):
    for rec in records:
        if rec.kind == "subject" and rec.error is None:
            parsed = parse_response(rec.raw_response, labels[rec.task])
            assert (parsed.label, parsed.parse_ok, parsed.format_ok) == (rec.parsed_label, rec.parse_ok, rec.format_ok)


def test_only_successful_subject_calls_are_scored(records):
    observations = observations_from_records(records, refusals={})
    assert len(observations) == 7 * 2 * 3  # probe, judge, and failed calls excluded


def test_majority_vote_breaks_ties_by_earliest_repeat():
    assert majority_vote([(0, "No"), (1, "Yes"), (2, "No")]) == "No"
    assert majority_vote([(2, "Jurisdiction"), (0, "Arbitration"), (1, "Other")]) == "Arbitration"
    assert majority_vote([(0, PARSE_FAIL), (1, PARSE_FAIL), (2, "Other")]) == PARSE_FAIL


def test_final_answers(answers):
    assert answers[("model_a", "tsr-3")].outcome == "No"
    assert not answers[("model_a", "tsr-3")].unanimous
    assert answers[("model_a", "tos-3")].outcome == "Arbitration"
    assert answers[("model_b", "tos-1")].outcome == "Arbitration"
    assert answers[("model_b", "tos-1")].format_ok_majority is False
    assert answers[("model_b", "tos-2")].outcome == PARSE_FAIL
    assert answers[("model_b", "tos-3")].outcome == REFUSAL


def test_accuracy_with_wilson_interval(metrics):
    assert metrics[("model_a", "tsr")].accuracy == pytest.approx(2 / 3)
    assert metrics[("model_a", "tos")].accuracy == pytest.approx(0.5)
    assert metrics[("model_b", "tos")].accuracy == pytest.approx(0.25)
    pooled_a = metrics[("model_a", ALL_TASKS)]
    assert (pooled_a.correct, pooled_a.n_cases) == (4, 7)
    assert pooled_a.accuracy_ci95 == pytest.approx(wilson_interval(4, 7))
    assert metrics[("model_b", ALL_TASKS)].correct == 3


def test_flag_rate_counts_positive_final_answers(metrics):
    assert metrics[("model_a", "tsr")].flag_rate == pytest.approx(1 / 3)
    assert metrics[("model_b", "tsr")].flag_rate == pytest.approx(1.0)
    assert metrics[("model_a", "tos")].flag_rate == pytest.approx(0.75)
    assert metrics[("model_b", "tos")].flag_rate == pytest.approx(0.5)  # parse failure and refusal are not flags
    assert metrics[("model_a", ALL_TASKS)].flag_rate == pytest.approx(4 / 7)
    assert metrics[("model_b", ALL_TASKS)].flag_rate == pytest.approx(5 / 7)


def test_per_label_precision_and_recall(metrics):
    tsr_a = metrics[("model_a", "tsr")].per_label
    assert tsr_a["Yes"] == {"precision": 1.0, "recall": 0.5, "predicted": 1, "support": 2}
    assert tsr_a["No"] == {"precision": 0.5, "recall": 1.0, "predicted": 2, "support": 1}
    tos_b = metrics[("model_b", "tos")].per_label
    assert tos_b["Other"] == {"precision": None, "recall": 0.0, "predicted": 0, "support": 2}
    assert tos_b["Jurisdiction"] == {"precision": 0.0, "recall": 0.0, "predicted": 1, "support": 1}
    assert metrics[("model_a", ALL_TASKS)].per_label is None


def test_call_level_failure_rates(metrics):
    tos_b = metrics[("model_b", "tos")]
    assert tos_b.n_calls == 12
    assert tos_b.parse_failure_rate == pytest.approx(2 / 12)
    assert tos_b.refusal_rate == pytest.approx(3 / 12)
    assert tos_b.format_violation_rate == pytest.approx(8 / 12)
    pooled_a = metrics[("model_a", ALL_TASKS)]
    assert (pooled_a.parse_failure_rate, pooled_a.refusal_rate, pooled_a.format_violation_rate) == (0, 0, 0)


def test_self_consistency_is_the_noise_floor(metrics):
    tsr_a = metrics[("model_a", "tsr")]
    assert tsr_a.unanimity_rate == pytest.approx(2 / 3)
    assert tsr_a.pairwise_agreement == pytest.approx(7 / 9)
    assert tsr_a.noise_floor == pytest.approx(2 / 9)
    assert tsr_a.repeat_accuracies == pytest.approx([2 / 3, 1.0, 2 / 3])
    assert metrics[("model_b", "tos")].unanimity_rate == pytest.approx(3 / 4)


def test_latency_uses_direct_calls_only(metrics):
    assert metrics[("model_a", "tsr")].mean_latency_ms == pytest.approx(2000.0)
    assert metrics[("model_a", "tsr")].latency_samples == 3
    assert metrics[("model_b", "tsr")].mean_latency_ms == pytest.approx(4000.0)  # the latency probe
    assert metrics[("model_a", "tos")].mean_latency_ms is None  # batch results carry no latency
    assert metrics[("model_b", ALL_TASKS)].mean_latency_ms == pytest.approx(4000.0)  # judge excluded


def test_token_totals(metrics):
    pooled_a = metrics[("model_a", ALL_TASKS)]
    assert pooled_a.total_input_tokens == 21 * 100
    assert pooled_a.total_output_tokens == 21 * 20
    assert pooled_a.mean_input_tokens == pytest.approx(100)


def test_refusal_decisions_override_the_api_stop_reason(records, gold):
    refusals = {"model_b|tos-2|0": True, "model_b|tos-2|1": True}
    refusals |= {f"model_b|tos-3|{r}": False for r in range(3)}
    answers = final_answers(observations_from_records(records, refusals), gold)
    assert answers[("model_b", "tos-2")].outcome == REFUSAL
    assert answers[("model_b", "tos-3")].outcome == PARSE_FAIL


def test_wilson_interval_known_values():
    assert wilson_interval(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)
    assert wilson_interval(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert mcnemar_exact(1, 9) == pytest.approx(22 / 1024)
    assert mcnemar_exact(4, 4) == 1.0
    assert mcnemar_exact(0, 0) == 1.0
