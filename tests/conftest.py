"""Shared fixtures: a 7-case, two-task synthetic run with three repeats per model.

Expected outcomes per case (model A -> model B):
  tsr-1 gold Yes:          Yes x3        -> Yes x3            same
  tsr-2 gold No:           No x3         -> Yes, Yes, No      A_right_B_wrong
  tsr-3 gold Yes:          No, Yes, No   -> Yes x3            A_wrong_B_right
  tos-1 gold Arbitration:  Arbitration   -> same label in ``` fences   format_drift
  tos-2 gold Other:        Other x3      -> prose, prose, Other       format_drift
  tos-3 gold Jurisdiction: 3-way tie     -> API refusal x3            refusal_change
  tos-4 gold Other:        Arbitration   -> Jurisdiction              both_wrong_differently
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from model_diff.record.schema import CallRecord
from model_diff.score.metrics import final_answers, observations_from_records

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def records() -> list[CallRecord]:
    lines = (FIXTURES / "calls_small.jsonl").read_text(encoding="utf-8").splitlines()
    return [CallRecord.model_validate_json(line) for line in lines]


@pytest.fixture
def gold() -> dict[str, str]:
    lines = (FIXTURES / "cases_small.jsonl").read_text(encoding="utf-8").splitlines()
    return {case["case_id"]: case["gold_label"] for case in map(json.loads, lines)}


@pytest.fixture
def labels() -> dict[str, list[str]]:
    spec = yaml.safe_load((FIXTURES / "tasks_small.yaml").read_text(encoding="utf-8"))["tasks"]
    return {task: s["labels"] for task, s in spec.items()}


@pytest.fixture
def positive() -> dict[str, set[str]]:
    spec = yaml.safe_load((FIXTURES / "tasks_small.yaml").read_text(encoding="utf-8"))["tasks"]
    return {task: set(s["positive_labels"]) for task, s in spec.items()}


@pytest.fixture
def answers(records, gold):
    return final_answers(observations_from_records(records, refusals={}), gold)
