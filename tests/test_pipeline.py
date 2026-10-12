"""Run, score, diff, report, and verify end to end against a fake client; no network.

The fake answers vary by arm in a known pattern (all cases have gold "Yes"):
  A, C  answer Yes everywhere.
  D     answers Yes, except case 4 where it replies in prose (unparseable).
  B     answers No on odd-numbered cases, prose on case 4, Yes otherwise.
"""

import re
from types import SimpleNamespace as NS

import pandas as pd
import pytest
from test_runner import SONNET_5_5, FakeMessages, runner, setup

from model_diff.pipeline import diff_run, report_run, score_run
from model_diff.record.chain import verify_run


class VariedMessages(FakeMessages):
    def reply(self, request):
        message = super().reply(request)
        system = request["system"]
        if system.startswith("You audit responses"):
            message.content[0].text = '{"refusal": false, "reason": "It attempted an answer."}'
        elif system.startswith("You compare two answers"):
            message.content[0].text = '{"nature": "stricter", "sentence": "B finds a violation where A did not."}'
        elif not system.startswith("Reply with"):
            case_number = int(request["messages"][0]["content"].split()[-1])
            sonnet_5_5 = request["model"] == SONNET_5_5
            arm_b = sonnet_5_5 and "thinking" not in request
            if sonnet_5_5 and case_number == 4:
                message.content[0].text = "I cannot help with that."
            elif arm_b and case_number % 2:
                message.content[0].text = '{"label": "No", "rationale": "r"}'
        return message


@pytest.fixture
def finished_run(tmp_path):
    # The cap must leave room for the judge reserve, or the cap guard rightly refuses to start.
    cfg, book, cases, run_dir = setup(tmp_path, cap=5.0, judge_budget=1.0)
    messages = VariedMessages()
    assert runner(cfg, book, cases, run_dir, messages).execute() == "complete"
    return run_dir, NS(messages=messages)


def test_score_diff_and_report_end_to_end(finished_run):
    run_dir, client = finished_run
    quiet = lambda _: None
    scores = score_run(run_dir, client, quiet)
    summary = diff_run(run_dir, client, quiet)
    report = report_run(run_dir).read_text()

    metrics = {(m["arm"], m["task"]): m for m in scores["metrics"]}
    assert metrics[("A", "ALL")]["accuracy"] == 1.0
    assert metrics[("B", "ALL")]["accuracy"] == pytest.approx(0.4)  # cases 0, 2, 6, 8 of each task
    assert metrics[("D", "ALL")]["accuracy"] == pytest.approx(0.9)
    assert scores["judge"]["asked_now"] == 8  # case 4 prose: 2 tasks x arms B and D x 2 repeats
    assert metrics[("B", "ALL")]["refusal_rate"] == 0  # the judge said those were attempts, not refusals

    headline = summary["pairs"]["A>B"]["categories"]
    assert headline == {"same": 8, "A_right_B_wrong": 10, "format_drift": 2}
    assert summary["judge_natures"] == {"stricter": 12}
    attribution = summary["attribution"]
    assert attribution["path"] == ["A", "C", "D", "B"]
    assert attribution["only"] == {"temperature": 0, "model": 2, "thinking": 10}

    diffs = pd.read_csv(run_dir / "diffs.csv")
    assert len(diffs) == 20 and set(diffs["judge_nature"].dropna()) == {"stricter"}
    sample = pd.read_csv(run_dir / "diffs_sample_for_review.csv", keep_default_na=False)
    assert len(sample) == 20 and (sample["category"] != "same").sum() == 12
    assert set(sample["human_verdict"]) == {""} and set(sample["notes"]) == {""}

    assert "Sequential attribution along the path A → C → D → B" in report
    assert "different order of changes" in report
    assert re.findall(r"(?<!\\)\$", report) == []  # every dollar sign escaped for math-rendering previews
    assert (run_dir / "accuracy_by_task.png").stat().st_size > 0
    assert (run_dir / "diff_categories_by_task.png").stat().st_size > 0
    assert verify_run(run_dir).ok  # judge calls joined the same chain


def test_judge_answers_are_reused_not_re_asked(finished_run):
    run_dir, client = finished_run
    quiet = lambda _: None
    score_run(run_dir, client, quiet)
    diff_run(run_dir, client, quiet)
    calls_before = len(client.messages.direct)
    assert score_run(run_dir, client, quiet)["judge"]["asked_now"] == 0
    assert diff_run(run_dir, client, quiet)["judge"]["asked_now"] == 0
    assert len(client.messages.direct) == calls_before


def test_report_needs_no_client(finished_run):
    run_dir, client = finished_run
    score_run(run_dir, client, lambda _: None)
    diff_run(run_dir, client, lambda _: None)
    assert report_run(run_dir).exists()  # report_run takes no client at all
