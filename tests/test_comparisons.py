from pathlib import Path

import pytest

from model_diff.config import load_config
from model_diff.report.comparisons import direction, model_only_pair, pair_stats, param_changes, reading
from model_diff.score.metrics import PARSE_FAIL, FinalAnswer

REPO = Path(__file__).resolve().parents[1]


def answers(rows: list[tuple[str, str, str, str]]) -> dict:
    """{(arm, case): FinalAnswer} from (case, gold, base outcome, other outcome) rows, arms X and Y."""
    out = {}
    for case_id, gold, x, y in rows:
        for arm, outcome in (("X", x), ("Y", y)):
            out[(arm, case_id)] = FinalAnswer(arm, "m", "t", case_id, gold, outcome, (outcome,) * 3, True, "")
    return out


def test_the_model_only_pair_is_the_model_step_of_the_path():
    cfg = load_config(REPO / "config.yaml")
    assert model_only_pair(cfg, ["A", "B", "C", "D"]) == ("C", "D")
    assert model_only_pair(cfg, ["A", "B", "C"]) is None  # arm D dropped: no model-only pair


def test_pair_stats_split_changes_and_count_discordant_cases():
    stats = pair_stats(answers([
        ("c1", "Yes", "Yes", "Yes"),
        ("c2", "Yes", "No", "Yes"),  # only Y right
        ("c3", "No", "No", "Yes"),  # only X right
        ("c4", "Yes", "Yes", PARSE_FAIL),  # only X right; one side gave no label
    ]), "X", "Y")
    assert (stats.n_cases, stats.changed, stats.label_changes, stats.no_label_changes) == (4, 3, 2, 1)
    assert (stats.only_base_right, stats.only_other_right) == (2, 1)
    assert stats.mcnemar_p == pytest.approx(1.0)


def test_direction_needs_enough_crossings_and_a_two_thirds_lean():
    rows = [(f"c{i}", "Yes", "No", "Yes") for i in range(4)] + [("c9", "Yes", "Yes", "No")]
    d = direction(answers(rows), "X", "Y", "t", {"Yes"})
    assert (d["toward"], d["away"], d["call"]) == (4, 1, "more flags")
    few = direction(answers(rows[:3]), "X", "Y", "t", {"Yes"})
    assert few["call"] == "too few changes to call"
    mixed = direction(answers(rows[:3] + [("c7", "Yes", "Yes", "No"), ("c8", "Yes", "Yes", "No")]), "X", "Y", "t", {"Yes"})
    assert mixed["call"] == "mixed"


def test_direction_separates_lateral_and_unlabelled_changes():
    d = direction(answers([("c1", "A", "Arbitration", "Jurisdiction"), ("c2", "A", "Other", PARSE_FAIL)]),
                  "X", "Y", "t", {"Arbitration", "Jurisdiction"})
    assert (d["toward"], d["away"], d["lateral"], d["no_label"]) == (0, 0, 1, 1)


def test_reading_maps_flag_direction_to_strictness_only_where_defined():
    assert reading("more flags", "more_flags") == "stricter"
    assert reading("fewer flags", "more_flags") == "more lenient"
    assert reading("fewer flags", "fewer_flags") == "stricter"
    assert reading("more flags", None) == "more flags"
    assert reading("mixed", "more_flags") == "mixed"


def test_param_changes_lists_every_differing_parameter():
    before = {"model": "m45", "max_tokens": 512, "temperature": 1.0}
    after = {"model": "m55", "max_tokens": 512, "thinking": {"type": "between_tools"}}
    assert param_changes(before, after) == [
        "model: m45 → m55",
        "temperature: 1.0 → not sent (API default)",
        "thinking: not sent (API default) → between_tools",
    ]
