"""The runner against a fake client shaped like the Anthropic SDK; no network."""

import datetime as dt
from pathlib import Path
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest
import yaml

from model_diff.config import load_config
from model_diff.data.cases import Case, write_cases
from model_diff.data.tasks import TaskSpec
from model_diff.prompts import PromptBook
from model_diff.record.chain import verify_run
from model_diff.runner import Runner, check_resumable, create_run_dir, decide

REPO = Path(__file__).resolve().parents[1]
SONNET_5_5 = "claude-sonnet-5-5"


def output_tokens(request: dict) -> int:
    """Sonnet 5.5 without a thinking setting (arm B) thinks; every other request answers in 50 tokens."""
    return 2000 if request["model"] == SONNET_5_5 and "thinking" not in request else 50


class FakeBatches:
    def __init__(self, messages, errored_ids, fail_create_after_storing=False):
        self.messages = messages
        self.errored_ids = set(errored_ids)
        self.fail_create_after_storing = fail_create_after_storing
        self.submitted: dict[str, list[dict]] = {}
        self.created_at: dict[str, dt.datetime] = {}

    def create(self, requests):
        batch_id = f"msgbatch_{len(self.submitted)}"
        self.submitted[batch_id] = list(requests)
        self.created_at[batch_id] = dt.datetime.now(dt.timezone.utc)
        if self.fail_create_after_storing:
            raise anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages/batches"))
        return NS(id=batch_id)

    def _counts(self, batch_id):
        return NS(processing=0, succeeded=len(self.submitted[batch_id]), errored=0, canceled=0, expired=0)

    def retrieve(self, batch_id):
        return NS(id=batch_id, processing_status="ended", request_counts=self._counts(batch_id))

    def list(self, limit=20):
        return [NS(id=b, created_at=self.created_at[b], request_counts=self._counts(b)) for b in self.submitted]

    def results(self, batch_id):
        for request in self.submitted[batch_id]:
            if request["custom_id"] in self.errored_ids:
                yield NS(custom_id=request["custom_id"], result=NS(type="errored"))
            else:
                yield NS(custom_id=request["custom_id"], result=NS(type="succeeded", message=self.messages.reply(request["params"])))


class FakeMessages:
    def __init__(self, wrong_model: bool = False, errored_ids=(), fail_create_after_storing=False):
        self.wrong_model = wrong_model
        self.direct: list[dict] = []
        self.batches = FakeBatches(self, errored_ids, fail_create_after_storing)
        self.count = 0

    def reply(self, request: dict):
        self.count += 1
        preflight = request["system"].startswith("Reply with the JSON object")
        text = '{"ok": true}' if preflight else '{"label": "Yes", "rationale": "r"}'
        out = output_tokens(request)
        thinking = out - 50 if out > 50 else None
        details = NS(thinking_tokens=thinking) if thinking is not None else None
        return NS(
            id=f"msg_{self.count}",
            model="claude-other" if self.wrong_model else request["model"],
            content=[NS(type="text", text=text)],
            stop_reason="end_turn",
            stop_details=None,
            usage=NS(input_tokens=100, output_tokens=out, output_tokens_details=details),
            _request_id=f"req_{self.count}",
        )

    def create(self, **request):
        self.direct.append(request)
        return self.reply(request)


def setup(tmp_path, cap: float = 1.0):
    base = load_config(REPO / "config.yaml")
    cfg = base.model_copy(
        update={
            "n_runs": 2,
            "cost_cap_usd": cap,
            "judge": base.judge.model_copy(update={"budget_usd": 0.0}),
            "paths": base.paths.model_copy(update={"runs": tmp_path / "runs"}),
            "run": base.run.model_copy(update={"poll_interval_s": 0, "pilot_fraction": 0.2, "latency_probe_cases": 2}),
        }
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(cfg.model_dump(mode="json")))
    tasks = {
        t: TaskSpec(family="consumer_protection_rule", labels=["Yes", "No"], positive_labels=["Yes"], license="CC BY 4.0")
        for t in ("t1", "t2")
    }
    book = PromptBook(REPO / "prompts", tasks)
    cases = [Case(case_id=f"{t}-{i:05d}", task=t, input=f"Facts {i}", gold_label="Yes", license="CC BY 4.0") for t in tasks for i in range(10)]
    source = tmp_path / "cases.jsonl"
    write_cases(source, cases)
    run_dir = create_run_dir(cfg, "test-run", {"cases.jsonl": source, "config.yaml": config_path}, book, {"models": []})
    return cfg, book, cases, run_dir


def runner(cfg, book, cases, run_dir, messages):
    return Runner(cfg, NS(messages=messages), run_dir, book, cases, echo=lambda _: None, sleep=lambda _: None)


def test_a_full_run_records_every_call_once_and_verifies(tmp_path):
    cfg, book, cases, run_dir = setup(tmp_path)
    messages = FakeMessages()
    run = runner(cfg, book, cases, run_dir, messages)
    assert run.execute() == "complete"

    records = run.recorder.records
    subject = [r for r in records if r.kind == "subject"]
    assert len(subject) == len({r.subject_key() for r in subject}) == 20 * 4 * 2
    assert len([r for r in records if r.kind == "latency_probe"]) == 4 * 2 * 2
    assert sorted(r.arm for r in records if r.kind == "preflight") == ["A", "B", "C", "D"]
    assert [len(reqs) for reqs in messages.batches.submitted.values()] == [32, 128]  # pilot, then the rest
    assert all(r.latency_ms is None for r in subject)
    assert all(r.latency_ms is not None for r in records if r.kind == "latency_probe")
    assert {r.thinking_tokens for r in subject if r.arm == "B"} == {1950}
    assert all(r.parsed_label == "Yes" and r.format_ok for r in subject)
    assert verify_run(run_dir).ok


def test_resuming_a_finished_run_sends_nothing(tmp_path):
    cfg, book, cases, run_dir = setup(tmp_path)
    messages = FakeMessages()
    runner(cfg, book, cases, run_dir, messages).execute()
    sent = (len(messages.direct), len(messages.batches.submitted))
    assert runner(cfg, book, cases, run_dir, messages).execute() == "complete"
    assert (len(messages.direct), len(messages.batches.submitted)) == sent


def test_errored_batch_items_fall_back_to_direct_calls(tmp_path):
    cfg, book, cases, run_dir = setup(tmp_path)
    run = runner(cfg, book, cases, run_dir, FakeMessages(errored_ids={"A-0-00000"}))
    assert run.execute() == "complete"
    retried = [r for r in run.recorder.records if r.kind == "subject" and r.subject_key() == "A|t1-00000|0"]
    assert len(retried) == 1 and retried[0].batch_id is None and retried[0].latency_ms is not None
    assert sum(outcomes.get("errored", 0) for outcomes in run.state["batch_outcomes"].values()) == 1


def test_a_batch_created_despite_a_failed_create_call_is_adopted_not_resubmitted(tmp_path):
    cfg, book, cases, run_dir = setup(tmp_path)
    messages = FakeMessages(fail_create_after_storing=True)
    run = runner(cfg, book, cases, run_dir, messages)
    assert run.execute() == "complete"
    assert len(messages.batches.submitted) == 2  # one pilot, one main: nothing resubmitted
    direct = [r for r in messages.direct if not r["system"].startswith("Reply with")]
    assert len(direct) == 4 * 2 * 2  # only the latency probes went direct


def test_a_projection_over_the_cap_stops_and_resumes_after_the_cap_is_raised(tmp_path):
    # Preflight and pilot cost about 0.12 USD; the projected total is about 0.57, or 0.56 without arm D.
    cfg, book, cases, run_dir = setup(tmp_path, cap=0.2)
    messages = FakeMessages()
    run = runner(cfg, book, cases, run_dir, messages)
    assert run.execute() == "stopped_over_cap"
    assert run.state["dropped_arms"] == ["D"]
    assert len(messages.batches.submitted) == 1
    assert run.state["projection"]["projected_total_usd"] > 0.2

    raised = cfg.model_copy(update={"cost_cap_usd": 1.0})
    check_resumable(run_dir, raised)
    assert runner(raised, book, cases, run_dir, messages).execute() == "complete"
    assert verify_run(run_dir).ok


def test_the_cap_guard_stops_before_a_batch_and_keeps_progress(tmp_path):
    cfg, book, cases, run_dir = setup(tmp_path, cap=0.01)  # preflight alone spends about 0.023 USD
    messages = FakeMessages()
    run = runner(cfg, book, cases, run_dir, messages)
    assert run.execute() == "stopped_cap_reached"
    assert run.state["status"] == "started" and "cap" in run.state["stopped"]["reason"]
    assert messages.batches.submitted == {}

    resumed = runner(cfg.model_copy(update={"cost_cap_usd": 1.0}), book, cases, run_dir, messages)
    assert resumed.execute() == "complete"
    assert len([r for r in resumed.recorder.records if r.kind == "preflight"]) == 4  # not repeated on resume
    assert verify_run(run_dir).ok


def test_decide_drops_arms_in_order_until_the_projection_fits():
    costs = {"A": 10, "B": 20, "C": 3, "D": 4}
    project = lambda arms: {"projected_total_usd": sum(costs[a] for a in arms)}
    assert decide(list(costs), ["D"], 40, project)[:2] == (["A", "B", "C", "D"], [])
    assert decide(list(costs), ["D"], 35, project)[:2] == (["A", "B", "C"], ["D"])
    kept, dropped, projection = decide(list(costs), ["D"], 30, project)
    assert dropped == ["D"] and projection["projected_total_usd"] == 33  # still over: the run stops


def test_a_response_from_another_model_stops_the_run(tmp_path):
    cfg, book, cases, run_dir = setup(tmp_path)
    run = runner(cfg, book, cases, run_dir, FakeMessages(wrong_model=True))
    assert run.execute() == "stopped_model_mismatch"
    assert run.recorder.records == []


def test_a_run_cannot_resume_under_different_pins_or_job_settings(tmp_path):
    cfg, _, _, run_dir = setup(tmp_path)
    check_resumable(run_dir, cfg)
    check_resumable(run_dir, cfg.model_copy(update={"cost_cap_usd": 99.0}))  # the cap may change
    with pytest.raises(SystemExit, match="different model ID"):
        check_resumable(run_dir, cfg.model_copy(update={"model_b": "claude-sonnet-5"}))
    with pytest.raises(SystemExit, match="n_runs"):
        check_resumable(run_dir, cfg.model_copy(update={"n_runs": 3}))
