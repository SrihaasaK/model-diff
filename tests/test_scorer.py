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
    reweighted_rate,
)
from model_diff.score.parse import parse_response
from model_diff.score.stats import mcnemar_exact, wilson_interval

# The "tos" fixture task is treated as sampled stratified from a source that is 90% Other.
NATURAL = {"tos": {"Other": 0.9, "Arbitration": 0.05, "Jurisdiction": 0.05}}


@pytest.fixture
def metrics(records, gold, labels, positive):
    observations = observations_from_records(records, refusals={})
    answers = final_answers(observations, gold)
    results = compute_metrics(answers, observations, latency_samples(records), labels, positive, NATURAL)
    return {(m.arm, m.task): m for m in results}


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
    assert answers[("A", "tsr-3")].outcome == "No"
    assert not answers[("A", "tsr-3")].unanimous
    assert answers[("A", "tos-3")].outcome == "Arbitration"
    assert answers[("B", "tos-1")].outcome == "Arbitration"
    assert answers[("B", "tos-1")].format_ok_majority is False
    assert answers[("B", "tos-2")].outcome == PARSE_FAIL
    assert answers[("B", "tos-3")].outcome == REFUSAL


def test_accuracy_with_wilson_interval(metrics):
    assert metrics[("A", "tsr")].accuracy == pytest.approx(2 / 3)
    assert metrics[("A", "tos")].accuracy == pytest.approx(0.5)
    assert metrics[("B", "tos")].accuracy == pytest.approx(0.25)
    pooled_a = metrics[("A", ALL_TASKS)]
    assert (pooled_a.correct, pooled_a.n_cases) == (4, 7)
    assert pooled_a.accuracy_ci95 == pytest.approx(wilson_interval(4, 7))
    assert metrics[("B", ALL_TASKS)].correct == 3


def test_flag_rate_counts_positive_final_answers(metrics):
    assert metrics[("A", "tsr")].flag_rate == pytest.approx(1 / 3)
    assert metrics[("B", "tsr")].flag_rate == pytest.approx(1.0)
    assert metrics[("A", "tos")].flag_rate == pytest.approx(0.75)
    assert metrics[("B", "tos")].flag_rate == pytest.approx(0.5)  # parse failure and refusal are not flags
    assert metrics[("A", ALL_TASKS)].flag_rate == pytest.approx(4 / 7)
    assert metrics[("B", ALL_TASKS)].flag_rate == pytest.approx(5 / 7)


def test_per_label_precision_and_recall(metrics):
    tsr_a = metrics[("A", "tsr")].per_label
    assert tsr_a["Yes"] == {"precision": 1.0, "recall": 0.5, "predicted": 1, "support": 2}
    assert tsr_a["No"] == {"precision": 0.5, "recall": 1.0, "predicted": 2, "support": 1}
    tos_b = metrics[("B", "tos")].per_label
    assert tos_b["Other"] == {"precision": None, "recall": 0.0, "predicted": 0, "support": 2}
    assert tos_b["Jurisdiction"] == {"precision": 0.0, "recall": 0.0, "predicted": 1, "support": 1}
    assert metrics[("A", ALL_TASKS)].per_label is None


def test_call_level_failure_rates(metrics):
    tos_b = metrics[("B", "tos")]
    assert tos_b.n_calls == 12
    assert tos_b.parse_failure_rate == pytest.approx(2 / 12)
    assert tos_b.refusal_rate == pytest.approx(3 / 12)
    assert tos_b.format_violation_rate == pytest.approx(8 / 12)
    pooled_a = metrics[("A", ALL_TASKS)]
    assert (pooled_a.parse_failure_rate, pooled_a.refusal_rate, pooled_a.format_violation_rate) == (0, 0, 0)


def test_self_consistency_is_the_noise_floor(metrics):
    tsr_a = metrics[("A", "tsr")]
    assert tsr_a.unanimity_rate == pytest.approx(2 / 3)
    assert tsr_a.pairwise_agreement == pytest.approx(7 / 9)
    assert tsr_a.noise_floor == pytest.approx(2 / 9)
    assert tsr_a.repeat_accuracies == pytest.approx([2 / 3, 1.0, 2 / 3])
    assert metrics[("B", "tos")].unanimity_rate == pytest.approx(3 / 4)


def test_latency_uses_direct_calls_only(metrics):
    assert metrics[("A", "tsr")].mean_latency_ms == pytest.approx(2000.0)
    assert metrics[("A", "tsr")].latency_samples == 3
    assert metrics[("B", "tsr")].mean_latency_ms == pytest.approx(4000.0)  # the latency probe
    assert metrics[("A", "tos")].mean_latency_ms is None  # batch results carry no latency
    assert metrics[("B", ALL_TASKS)].mean_latency_ms == pytest.approx(4000.0)  # judge excluded


def test_token_totals(metrics):
    pooled_a = metrics[("A", ALL_TASKS)]
    assert pooled_a.total_input_tokens == 21 * 100
    assert pooled_a.total_output_tokens == 21 * 20
    assert pooled_a.mean_input_tokens == pytest.approx(100)


def test_refusal_decisions_override_the_api_stop_reason(records, gold):
    refusals = {"B|tos-2|0": True, "B|tos-2|1": True}
    refusals |= {f"B|tos-3|{r}": False for r in range(3)}
    answers = final_answers(observations_from_records(records, refusals), gold)
    assert answers[("B", "tos-2")].outcome == REFUSAL
    assert answers[("B", "tos-3")].outcome == PARSE_FAIL


def test_flag_rate_and_accuracy_reweighted_to_the_natural_label_mix(metrics):
    # Model A on tos, by gold label: Other cases flagged 1 of 2 and correct 1 of 2;
    # the Arbitration case is flagged and correct; the Jurisdiction case is flagged and wrong.
    tos_a = metrics[("A", "tos")]
    assert tos_a.flag_rate_natural == pytest.approx(0.9 * 0.5 + 0.05 * 1 + 0.05 * 1)
    assert tos_a.accuracy_natural == pytest.approx(0.9 * 0.5 + 0.05 * 1 + 0.05 * 0)
    assert metrics[("A", "tsr")].flag_rate_natural is None  # sampled at random: no reweighting
    assert metrics[("A", ALL_TASKS)].flag_rate_natural is None


def test_reweighting_renormalizes_over_labels_present_in_the_sample(answers):
    tos = [a for (arm, _), a in answers.items() if arm == "A" and a.task == "tos"]
    shares = {"Other": 0.6, "Arbitration": 0.2, "Jurisdiction": 0.1, "Content removal": 0.1}
    rate = reweighted_rate(tos, shares, lambda a: a.correct)
    assert rate == pytest.approx((0.6 * 0.5 + 0.2 * 1 + 0.1 * 0) / 0.9)
    assert reweighted_rate(tos, {"Unseen": 1.0}, lambda a: a.correct) is None


def test_thinking_tokens_are_averaged_where_reported(metrics):
    assert metrics[("B", "tsr")].mean_thinking_tokens == pytest.approx(50)
    assert metrics[("A", "tsr")].mean_thinking_tokens is None


def test_wilson_interval_known_values():
    assert wilson_interval(5, 10) == pytest.approx((0.2366, 0.7634), abs=1e-4)
    assert wilson_interval(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert mcnemar_exact(1, 9) == pytest.approx(22 / 1024)
    assert mcnemar_exact(4, 4) == 1.0
    assert mcnemar_exact(0, 0) == 1.0
