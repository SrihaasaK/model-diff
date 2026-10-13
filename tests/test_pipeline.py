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

from model_diff.pipeline import describe_sample, diff_run, publish_run, reliability_run, report_run, score_run
from model_diff.record.chain import verify_run
from model_diff.score.reliability import DIRECTION_RULE


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
    # The review sample comes from the model-only pair (C vs D), which differs only on case 4 of each task.
    sample = pd.read_csv(run_dir / "diffs_sample_for_review.csv", keep_default_na=False)
    assert list(sample["category"]) == ["format_drift", "format_drift"]
    assert set(sample["judge_nature"]) == {"not_judged"}  # no judge call is made for the model-only pair
    assert set(sample["human_verdict"]) == {""} and set(sample["notes"]) == {""}
    assert len(pd.read_csv(run_dir / "diffs_C_vs_D.csv")) == 20

    assert "## Primary comparison: the model switch alone (arm C vs arm D)" in report
    assert "## What a vendor sees if it does not pin settings (arm A vs arm B)" in report
    assert "mean latency" not in report.lower()  # latency rows are dropped; probe spend stays in the cost table
    assert "different order of changes" in report
    attribution = (run_dir / "attribution.md").read_text()
    assert "the model step alone moved 2" in attribution and "the thinking step alone moved 10" in attribution
    per_task = (run_dir / "per_task.md").read_text()
    assert "| `t1` | CC BY 4.0 | 10 | 100.0% | 90.0% | -10.0 pts |" in per_task
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


def test_describing_the_sample_asks_once_per_row_and_keeps_human_entries(finished_run):
    run_dir, client = finished_run
    quiet = lambda _: None
    score_run(run_dir, client, quiet)
    diff_run(run_dir, client, quiet)
    path = run_dir / "diffs_sample_for_review.csv"
    sample = pd.read_csv(path, keep_default_na=False, dtype=str)
    sample.loc[0, "human_verdict"], sample.loc[0, "notes"] = "format_change", "checked"
    sample.loc[0, "rule_label"], sample.loc[0, "rule_note"] = "other", "first pass"
    sample.to_csv(path, index=False)

    assert describe_sample(run_dir, client, quiet) == 2  # the two model-only changes in the sample
    assert describe_sample(run_dir, client, quiet) == 0  # recorded answers are reused
    after = pd.read_csv(path, keep_default_na=False, dtype=str)
    assert set(after["judge_nature"]) == {"stricter"}
    assert (after.loc[0, "human_verdict"], after.loc[0, "notes"]) == ("format_change", "checked")
    assert (after.loc[0, "rule_label"], after.loc[0, "rule_note"]) == ("other", "first pass")
    assert verify_run(run_dir).ok


def test_judge_reliability_reaches_the_report_with_method_rule_and_caveat(finished_run, monkeypatch):
    run_dir, client = finished_run
    monkeypatch.setattr("model_diff.score.reliability.DIRECTION_READINGS",
                        {"t1": "Reading for t1.", "absent_task": "Never shown."})
    quiet = lambda _: None
    score_run(run_dir, client, quiet)
    diff_run(run_dir, client, quiet)
    describe_sample(run_dir, client, quiet)
    path = run_dir / "diffs_sample_for_review.csv"
    sample = pd.read_csv(path, keep_default_na=False, dtype=str)
    sample["rule_label"] = ["stricter", "stricter"]
    sample.loc[0, "human_verdict"] = "stricter"
    sample.to_csv(path, index=False)
    with pytest.raises(SystemExit):
        reliability_run(run_dir)  # row 2 has no confirmed label yet

    sample.loc[1, "human_verdict"], sample.loc[1, "notes"] = "format_change", "fence only"
    sample.to_csv(path, index=False)
    with pytest.raises(ValueError):
        reliability_run(run_dir, held=("stricter",))  # 1 of 2 does not support "held"
    calls = len(client.messages.direct)
    rel = reliability_run(run_dir, differ_caveat="The differ misses reasoning changes.")
    assert len(client.messages.direct) == calls  # offline
    assert (rel["agree"], rel["n_reviewed"], rel["judge_overridden"], rel["rule_overridden"]) == (1, 2, 1, 1)
    assert rel["pair"] == "arm C vs arm D"

    report = report_run(run_dir).read_text()
    assert "## Judge reliability" in report and "**1 of 2 cases (50.0%)**" in report
    assert "not blind to the judge's labels" in report
    assert "independent human" not in report
    assert "6. Judge reliability: Reference labels are a rule-based first pass" in report
    assert "resolved individually by the author. Reading for t1." in report  # only tasks the run includes
    assert "Never shown." not in report and rel["direction_readings"] == {"t1": "Reading for t1."}
    assert "- **Differ.** The differ misses reasoning changes." in report
    row_two = sample.loc[1, "case_id"]
    assert f"| 2 | `{row_two}` | format_drift | stricter | format_change | fence only |" in report
    for line in DIRECTION_RULE:
        assert f"- {line}" in report


def test_report_needs_no_client(finished_run):
    run_dir, client = finished_run
    score_run(run_dir, client, lambda _: None)
    diff_run(run_dir, client, lambda _: None)
    assert report_run(run_dir).exists()  # report_run takes no client at all


def test_offline_scoring_and_publishing_make_no_calls_and_publish_no_case_text(finished_run, tmp_path):
    run_dir, client = finished_run
    quiet = lambda _: None
    score_run(run_dir, client, quiet)
    diff_run(run_dir, client, quiet)
    calls = len(client.messages.direct)
    score_run(run_dir, None, quiet)
    diff_run(run_dir, None, quiet)
    report_run(run_dir)
    assert len(client.messages.direct) == calls
    published = publish_run(run_dir, tmp_path / "public")
    readme = (tmp_path / "public" / "README.md").read_text()
    assert verify_run(run_dir).head in readme and "uv run model-diff verify test-run" in readme
    assert "These files hold no case text and no model responses" in readme
    for path in published:
        if path.suffix in (".md", ".json"):
            assert "Facts " not in path.read_text()  # case inputs are "Facts <n>"
            assert '"label": "Yes"' not in path.read_text()  # no model responses

    (run_dir / "examples.md").write_text("vetted examples")
    publish_run(run_dir, tmp_path / "public")
    readme = (tmp_path / "public" / "README.md").read_text()
    assert "Apart from `examples.md`, which quotes a few vetted public cases" in readme
    assert "- `examples.md`" in readme
