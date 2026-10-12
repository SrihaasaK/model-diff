from collections import Counter

import pytest

from model_diff.diff.differ import (
    CATEGORIES,
    DiffRow,
    allocate,
    classify,
    decompose,
    diff_answers,
    final_disagreement,
    review_sample,
    single_run_disagreement,
)
from model_diff.score.metrics import ALL_TASKS, PARSE_FAIL, REFUSAL, FinalAnswer

EXPECTED = {
    "tsr-1": "same",
    "tsr-2": "A_right_B_wrong",
    "tsr-3": "A_wrong_B_right",
    "tos-1": "format_drift",
    "tos-2": "format_drift",
    "tos-3": "refusal_change",
    "tos-4": "both_wrong_differently",
}


def answer(outcome: str, gold: str = "Yes", format_ok: bool = True) -> FinalAnswer:
    return FinalAnswer("model_x", "m", "t", "c", gold, outcome, (outcome,) * 3, format_ok, "")


def test_fixture_cases_land_in_expected_categories(answers):
    rows = diff_answers(answers, "A", "B")
    assert {r.case_id: r.category for r in rows} == EXPECTED
    assert set(EXPECTED.values()) == set(CATEGORIES)


def test_refusal_change_takes_precedence_over_format_drift():
    assert classify(answer(PARSE_FAIL), answer(REFUSAL)) == "refusal_change"


def test_both_unparseable_or_both_refusing_is_same():
    assert classify(answer(PARSE_FAIL, format_ok=False), answer(PARSE_FAIL, format_ok=False)) == "same"
    assert classify(answer(REFUSAL, format_ok=False), answer(REFUSAL, format_ok=False)) == "same"


def test_same_label_with_broken_strict_format_is_format_drift():
    assert classify(answer("Yes", format_ok=True), answer("Yes", format_ok=False)) == "format_drift"
    assert classify(answer("Yes"), answer("Yes")) == "same"


def test_rows_carry_votes_and_representative_responses(answers):
    row = next(r for r in diff_answers(answers, "A", "B") if r.case_id == "tsr-2")
    assert (row.a_votes, row.b_votes) == ("No|No|No", "Yes|Yes|No")
    assert row.b_response == '{"label": "Yes", "rationale": "r"}'
    assert (row.judge_nature, row.judge_sentence) == ("", "")


def test_incomplete_runs_are_rejected(answers):
    del answers[("B", "tsr-1")]
    with pytest.raises(ValueError, match="lack an answer from one of"):
        diff_answers(answers, "A", "B")


def test_single_run_disagreement(answers):
    disagreement = single_run_disagreement(answers, "A", "B")
    assert disagreement["tsr"] == pytest.approx(4 / 9)
    assert disagreement["tos"] == pytest.approx(2 / 3)
    assert disagreement[ALL_TASKS] == pytest.approx(4 / 7)


def test_final_disagreement(answers):
    disagreement = final_disagreement(answers, "A", "B")
    assert disagreement["tsr"] == pytest.approx(2 / 3)
    assert disagreement["tos"] == pytest.approx(3 / 4)
    assert disagreement[ALL_TASKS] == pytest.approx(5 / 7)


def path_answers(rows: dict[str, tuple[str, str, str, str]]) -> dict:
    """Final answers for arms A, C, D, B from {case: (A, C, D, B)} outcomes."""
    answers = {}
    for case_id, outcomes in rows.items():
        for arm, outcome in zip("ACDB", outcomes):
            answers[(arm, case_id)] = FinalAnswer(arm, "m", "t", case_id, "Yes", outcome, (outcome,) * 3, True, "")
    return answers


def test_decompose_attributes_each_changed_case_to_the_steps_that_moved_it():
    answers = path_answers(
        {
            "c1": ("Yes", "Yes", "Yes", "No"),  # thinking only
            "c2": ("Yes", "No", "No", "No"),  # temperature only
            "c3": ("Yes", "Yes", "No", "No"),  # model only
            "c4": ("Yes", "No", "Yes", "No"),  # every step moved it
            "c5": ("Yes", "No", "Yes", "Yes"),  # moved and moved back: no A-vs-B change
            "c6": ("No", "No", "No", "No"),
        }
    )
    result = decompose(answers, ["A", "C", "D", "B"], ["temperature", "model", "thinking"])
    assert (result["n_cases"], result["n_changed"]) == (6, 4)
    assert result["only"] == {"temperature": 1, "model": 1, "thinking": 1}
    assert result["involved"] == {"temperature": 2, "model": 2, "thinking": 2}
    assert result["combinations"] == {"model": 1, "temperature": 1, "temperature+model+thinking": 1, "thinking": 1}
    finals = [step["final_disagreement"] for step in result["steps"]]
    assert finals == pytest.approx([3 / 6, 3 / 6, 2 / 6])
    assert [(s["from"], s["to"]) for s in result["steps"]] == [("A", "C"), ("C", "D"), ("D", "B")]


def test_decompose_requires_every_arm_on_the_path():
    answers = path_answers({"c1": ("Yes", "Yes", "Yes", "No")})
    del answers[("D", "c1")]
    with pytest.raises(ValueError, match="lack an answer"):
        decompose(answers, ["A", "C", "D", "B"], ["temperature", "model", "thinking"])


def test_allocate_gives_each_category_a_slot_then_proportional_shares():
    assert allocate({"a": 3, "b": 2}, 30) == {"a": 3, "b": 2}
    assert allocate({"x": 100, "y": 10, "z": 1, "w": 0}, 30) == {"x": 26, "y": 3, "z": 1, "w": 0}


def synthetic_rows() -> list[DiffRow]:
    counts = {
        "same": 60,
        "A_right_B_wrong": 30,
        "A_wrong_B_right": 20,
        "both_wrong_differently": 6,
        "format_drift": 3,
        "refusal_change": 1,
    }
    rows, i = [], 0
    for category, count in counts.items():
        for _ in range(count):
            task = ("t1", "t2", "t3")[i % 3]
            rows.append(DiffRow(f"{task}-{i:03d}", task, "Yes", "Yes", "No", "", "", category, True, True, "", ""))
            i += 1
    return rows


def test_review_sample_is_stratified_seeded_and_spread_across_tasks():
    rows = synthetic_rows()
    first = review_sample(rows, n=30, seed=42)
    again = review_sample(rows, n=30, seed=42)
    assert len(first) == 30
    assert [r.case_id for r in first] == [r.case_id for r in again]
    counts = Counter(r.category for r in first)
    assert "same" not in counts
    assert set(counts) == set(CATEGORIES) - {"same"}
    assert counts["refusal_change"] == 1
    assert {r.task for r in first} == {"t1", "t2", "t3"}


def test_review_sample_tops_up_with_unchanged_cases_when_few_differ():
    rows = [r for r in synthetic_rows() if r.category in ("same", "format_drift")]
    sample = review_sample(rows, n=30, seed=42)
    counts = Counter(r.category for r in sample)
    assert counts == {"format_drift": 3, "same": 27}
