import pytest

from model_diff.report.report import label_reading_sentences
from model_diff.score.reliability import DIRECTION_READINGS, DIRECTION_RULE, METHOD, agreement, label_reading


def row(n: int, judge: str, rule: str, human: str, notes: str = "") -> dict:
    return {"row": n, "case_id": f"c{n}", "task": "t", "category": "cat", "judge_nature": judge,
            "rule_label": rule, "human_verdict": human, "notes": notes}


def test_agreement_overall_per_label_and_overrides():
    rows = [
        row(1, "stricter", "stricter", "stricter"),
        row(2, "stricter", "more_lenient", "more_lenient", "rule table"),
        row(3, "judge_unparseable", "other", "other"),
        row(4, "other", "format_change", "other", "reviewer override"),
    ]
    result = agreement(rows)
    assert (result["agree"], result["n_reviewed"], result["n_judged"]) == (2, 4, 3)
    assert result["agreement"] == pytest.approx(0.5)
    assert result["agreement_judged"] == pytest.approx(2 / 3)
    assert result["per_judge_label"] == {
        "judge_unparseable": {"n": 1, "agree": 0},
        "other": {"n": 1, "agree": 1},
        "stricter": {"n": 2, "agree": 1},
    }
    assert [d["case_id"] for d in result["disagreements"]] == ["c2", "c3"]
    assert (result["judge_overridden"], result["rule_overridden"]) == (2, 1)


def test_unreviewed_rows_are_left_out():
    result = agreement([row(1, "stricter", "stricter", "stricter"), row(2, "other", "other", "")])
    assert (result["n"], result["n_reviewed"], result["agree"]) == (2, 1, 1)


def test_method_wording_states_the_labels_were_not_blind():
    assert "rule-based first pass by the harness author's agent" in METHOD
    assert "not blind to the judge's labels" in METHOD
    assert len(DIRECTION_RULE) == 5


PER_LABEL = {
    "format_change": {"n": 4, "agree": 4},
    "misread_instruction": {"n": 3, "agree": 0},
    "more_lenient": {"n": 7, "agree": 7},
    "other": {"n": 7, "agree": 5},
    "stricter": {"n": 8, "agree": 7},
}


def test_label_reading_is_refused_where_the_counts_contradict_it():
    assert label_reading(PER_LABEL, ["misread_instruction"], ["stricter", "more_lenient"]) == {
        "unreliable": ["misread_instruction"], "held": ["stricter", "more_lenient"]}
    with pytest.raises(ValueError, match="does not support calling it unreliable"):
        label_reading(PER_LABEL, ["stricter"], [])
    with pytest.raises(ValueError, match="does not support saying it held"):
        label_reading(PER_LABEL, [], ["misread_instruction"])
    with pytest.raises(ValueError, match="does not support saying it held"):
        label_reading({"x": {"n": 2, "agree": 1}}, [], ["x"])  # an even split supports neither reading
    with pytest.raises(ValueError, match="not a judge label"):
        label_reading(PER_LABEL, ["refusal"], [])


def test_label_reading_sentences_carry_the_counts_and_name_other_perfect_labels():
    rel = {"per_judge_label": PER_LABEL,
           "label_reading": label_reading(PER_LABEL, ["misread_instruction"], ["stricter", "more_lenient"])}
    assert label_reading_sentences(rel) == [
        "The judge's `misread_instruction` label matched 0 of 3 reference labels and should be treated as unreliable.",
        "`stricter` (7 of 8) and `more_lenient` (7 of 7) are the labels that held; "
        "`format_change` also matched all 4 of its uses.",
    ]
    assert label_reading_sentences({"per_judge_label": PER_LABEL}) == []


def test_privacy_policy_reading_is_the_authors_sentence():
    assert DIRECTION_READINGS["privacy_policy_qa"] == (
        'On `privacy_policy_qa`, the direction rule is read as "more likely to mark Relevant = more_lenient," since '
        '"more flags" and "requires more before accepting" diverge on relevance tasks.')
