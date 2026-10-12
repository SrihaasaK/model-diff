import hashlib
from collections import Counter
from pathlib import Path

import pytest

from model_diff.data.cases import Case, JsonlAdapter, read_cases, task_labels, write_cases
from model_diff.data.legalbench import LegalBenchAdapter, compose_input
from model_diff.data.propose import _screened_entry, is_noncommercial, screen
from model_diff.data.sample import sample_cases
from model_diff.data.tasks import TaskFile, TaskSpec, load_tasks, require_approval

REPO = Path(__file__).resolve().parents[1]


def pool(task: str, labels: dict[str, int]) -> list[Case]:
    cases, i = [], 0
    for label, count in labels.items():
        for _ in range(count):
            cases.append(Case(case_id=f"{task}-{i:05d}", task=task, input=f"text {i}", gold_label=label, license="MIT"))
            i += 1
    return cases


def spec(sampling: str = "random", labels=("Yes", "No")) -> TaskSpec:
    return TaskSpec(family="f", labels=list(labels), sampling=sampling)


def test_random_sampling_is_seeded_and_independent_of_input_order():
    cases = pool("t", {"Yes": 300, "No": 300})
    first = sample_cases(cases, {"t": spec()}, per_task=50, seed=42)
    shuffled = sample_cases(list(reversed(cases)), {"t": spec()}, per_task=50, seed=42)
    other_seed = sample_cases(cases, {"t": spec()}, per_task=50, seed=7)
    assert [c.case_id for c in first] == [c.case_id for c in shuffled]
    assert [c.case_id for c in first] != [c.case_id for c in other_seed]
    assert len(first) == 50


def test_adding_a_task_does_not_change_another_tasks_sample():
    a = pool("a", {"Yes": 100, "No": 100})
    b = pool("b", {"Yes": 100, "No": 100})
    alone = sample_cases(a, {"a": spec()}, 20, 42)
    together = [c for c in sample_cases(a + b, {"a": spec(), "b": spec()}, 20, 42) if c.task == "a"]
    assert [c.case_id for c in alone] == [c.case_id for c in together]


def test_small_tasks_are_used_whole():
    cases = pool("t", {"Yes": 30, "No": 17})
    assert len(sample_cases(cases, {"t": spec()}, per_task=200, seed=42)) == 47


def test_stratified_sampling_gives_equal_shares_and_redistributes_spare_slots():
    labels = ("Other", "Arbitration", "Jurisdiction")
    cases = pool("t", {"Other": 900, "Arbitration": 5, "Jurisdiction": 60})
    picked = sample_cases(cases, {"t": spec("stratified", labels)}, per_task=60, seed=42)
    counts = Counter(c.gold_label for c in picked)
    assert counts == {"Arbitration": 5, "Jurisdiction": 28, "Other": 27}


def test_jsonl_corpus_round_trips_and_rejects_duplicates(tmp_path):
    cases = pool("custom_task", {"Approve": 2, "Escalate": 1})
    path = tmp_path / "corpus.jsonl"
    write_cases(path, cases)
    assert JsonlAdapter(path).load_pool() == cases
    assert read_cases(path) == cases
    path.write_text(path.read_text() + path.read_text().splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="duplicate case_id"):
        JsonlAdapter(path).load_pool()


def test_jsonl_corpus_rejects_unknown_fields(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text('{"case_id": "x", "task": "t", "input": "i", "gold_label": "A", "license": "L", "extra": 1}\n')
    with pytest.raises(ValueError):
        JsonlAdapter(path).load_pool()


def test_label_sets_fall_back_to_gold_labels_for_undeclared_tasks():
    cases = pool("custom", {"Escalate": 1, "Approve": 2})
    assert task_labels(cases, declared={}) == {"custom": ["Approve", "Escalate"]}
    assert task_labels(cases, declared={"custom": ["Escalate", "Approve", "Hold"]}) == {
        "custom": ["Escalate", "Approve", "Hold"]
    }


def test_compose_input_joins_columns_under_headings():
    row = {"policy": "  Covers fire. ", "claim": "House burned.", "text": "Plain."}
    assert compose_input(row, [("policy", "Policy"), ("claim", "Claim")]) == "Policy:\nCovers fire.\n\nClaim:\nHouse burned."
    assert compose_input(row, [("text", "")]) == "Plain."


def test_legalbench_rows_map_dataset_codes_to_labels():
    task_spec = TaskSpec(
        family="insurance_coverage",
        labels=["Yes", "No", "Ambiguous"],
        label_map={"A": "Yes", "B": "No", "C": "Ambiguous"},
        input_fields=[("policy", "Policy"), ("claim", "Claim")],
        license="CC BY 4.0",
    )
    adapter = LegalBenchAdapter("nguha/legalbench", "rev", "test", {"ins": task_spec})
    case = adapter.to_case("ins", {"index": 7, "policy": "P", "claim": "C", "answer": "C"})
    assert case == Case(case_id="ins-00007", task="ins", input="Policy:\nP\n\nClaim:\nC", gold_label="Ambiguous", license="CC BY 4.0")
    with pytest.raises(ValueError, match="not in"):
        adapter.to_case("ins", {"index": 8, "policy": "P", "claim": "C", "answer": "D"})


def test_repository_task_file_is_valid_and_unapproved_blocks_paid_steps():
    path = REPO / "data" / "tasks.yaml"
    task_file = load_tasks(path)
    assert 4 <= len(task_file.tasks) <= 6
    for task_spec in task_file.tasks.values():
        assert all(isinstance(label, str) for label in task_spec.labels)
        assert task_spec.license and task_spec.justification and task_spec.input_fields
        assert not is_noncommercial(task_spec.license)
    with pytest.raises(SystemExit, match="not approved"):
        require_approval(TaskFile(approved=False, tasks=task_file.tasks), path)
    require_approval(TaskFile(approved=True, tasks=task_file.tasks), path)


def test_task_spec_rejects_flag_labels_outside_the_label_set():
    with pytest.raises(ValueError, match="not in the task's label set"):
        TaskSpec(family="f", labels=["Yes", "No"], positive_labels=["Maybe"])


def test_screened_entries_match_by_name_prefix_or_identifier_hash():
    digest = hashlib.sha256(b"example_withheld_task").hexdigest()
    task_file = TaskFile(
        tasks={},
        screened_out=[
            {"match": "opp115_", "reason": "nc"},
            {"match": "exact_task", "reason": "exact"},
            {"match_sha256": digest, "display": "(withheld)", "reason": "name"},
        ],
    )
    assert _screened_entry("opp115_data_retention", task_file)["reason"] == "nc"
    assert _screened_entry("exact_task", task_file)["reason"] == "exact"
    assert _screened_entry("exact_task_two", task_file) is None
    assert _screened_entry("example_withheld_task", task_file)["display"] == "(withheld)"


def test_domain_screen_requires_topic_and_small_categorical_answer_space():
    metadata = {
        "privacy_task": {"instruction": "Does the clause describe data retention?", "answer_space": ["Yes", "No"]},
        "numeric_tax": {"instruction": "Compute the tax owed.", "answer_space": []},
        "off_topic": {"instruction": "Is this hearsay?", "answer_space": ["Yes", "No"]},
    }
    assert screen(metadata) == ["privacy_task"]
    assert is_noncommercial("CC BY-NC 4.0") and is_noncommercial("Creative Commons Attribution-NonCommercial License")
    assert not is_noncommercial("CC BY 4.0") and not is_noncommercial("MIT")
