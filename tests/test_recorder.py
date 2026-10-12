import json

import pytest

from model_diff.hashing import sha256_file
from model_diff.record.chain import verify_run
from model_diff.record.recorder import ModelPinError, Recorder
from model_diff.record.schema import CallRecord


def make_run(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    (run_dir / "cases.jsonl").write_text('{"case_id": "c1"}\n')
    config = {
        "run_id": "run1",
        "pinned_models": ["model-x", "judge-y"],
        "artifacts": {"cases.jsonl": sha256_file(run_dir / "cases.jsonl")},
    }
    (run_dir / "run_config.json").write_text(json.dumps(config))
    return run_dir


def record(i: int, model: str = "model-x", response_model: str | None = None) -> CallRecord:
    return CallRecord(
        run_id="run1", case_id=f"c{i}", task="t", model_id=model, params={"model": model},
        prompt_sha256="0" * 64, request_id=None, raw_response='{"label": "Yes", "rationale": "r"}',
        parsed_label="Yes", parse_ok=True, input_tokens=10, output_tokens=5, latency_ms=None,
        timestamp="2026-10-12T00:00:00+00:00", sdk_version="1.13.0", repeat_index=0,
        arm="A", kind="subject", format_ok=True, response_model=response_model or model,
    )


def filled(tmp_path, n: int = 3):
    run_dir = make_run(tmp_path)
    recorder = Recorder(run_dir)
    for i in range(n):
        recorder.append(record(i))
    return run_dir


def rewrite_lines(path, transform):
    path.write_text("".join(line + "\n" for line in transform(path.read_text().splitlines())))


def test_an_intact_run_verifies(tmp_path):
    run_dir = filled(tmp_path)
    result = verify_run(run_dir)
    assert result.ok, result.problems
    assert result.records == 3
    assert result.head == Recorder(run_dir).head


def test_reopening_a_run_continues_the_chain(tmp_path):
    run_dir = filled(tmp_path, 2)
    Recorder(run_dir).append(record(9))
    result = verify_run(run_dir)
    assert result.ok, result.problems
    assert result.records == 3


def test_an_edited_record_is_detected(tmp_path):
    run_dir = filled(tmp_path)
    rewrite_lines(run_dir / "calls.jsonl", lambda lines: [lines[0], lines[1].replace('"Yes"', '"No"', 1), lines[2]])
    assert any("record 1" in p and "altered" in p for p in verify_run(run_dir).problems)


def test_truncating_both_files_is_detected(tmp_path):
    run_dir = filled(tmp_path)
    for name in ("calls.jsonl", "manifest.jsonl"):
        rewrite_lines(run_dir / name, lambda lines: lines[:-1])
    assert any("truncated" in p for p in verify_run(run_dir).problems)


def test_deleting_a_middle_record_breaks_the_chain(tmp_path):
    run_dir = filled(tmp_path)
    for name in ("calls.jsonl", "manifest.jsonl"):
        rewrite_lines(run_dir / name, lambda lines: [lines[0], lines[2]])
    problems = verify_run(run_dir).problems
    assert any("does not chain" in p for p in problems)
    assert any("removed or reordered" in p for p in problems)


def test_a_changed_frozen_artifact_is_detected(tmp_path):
    run_dir = filled(tmp_path)
    (run_dir / "cases.jsonl").write_text('{"case_id": "c2"}\n')
    assert any("cases.jsonl" in p for p in verify_run(run_dir).problems)


def test_an_edited_run_config_breaks_the_first_link(tmp_path):
    run_dir = filled(tmp_path)
    config = json.loads((run_dir / "run_config.json").read_text())
    config["pinned_models"].append("model-z")
    (run_dir / "run_config.json").write_text(json.dumps(config))
    assert any("manifest line 0 does not chain" in p for p in verify_run(run_dir).problems)


def test_unpinned_or_substituted_models_are_refused(tmp_path):
    run_dir = make_run(tmp_path)
    recorder = Recorder(run_dir)
    with pytest.raises(ModelPinError):
        recorder.append(record(0, model="model-z"))
    with pytest.raises(ModelPinError):
        recorder.append(record(0, response_model="model-other"))
    assert not (run_dir / "calls.jsonl").exists()


@pytest.mark.parametrize("crash_after", ["calls", "manifest"])
def test_an_append_cut_short_by_a_crash_is_set_aside_on_reopening(tmp_path, crash_after):
    run_dir = filled(tmp_path, 2)
    # An identical run with a third record supplies the lines a third append would write.
    (tmp_path / "scratch").mkdir()
    scratch = filled(tmp_path / "scratch", 3)
    with open(run_dir / "calls.jsonl", "a") as fh:
        fh.write((scratch / "calls.jsonl").read_text().splitlines()[2] + "\n")
    if crash_after == "manifest":
        with open(run_dir / "manifest.jsonl", "a") as fh:
            fh.write((scratch / "manifest.jsonl").read_text().splitlines()[2] + "\n")

    recorder = Recorder(run_dir)  # HEAD.json still says 2 records
    assert recorder.count == 2
    assert len((run_dir / "orphans.jsonl").read_text().splitlines()) == 1
    recorder.append(record(5))
    assert verify_run(run_dir).ok


def test_mismatched_file_lengths_block_reopening(tmp_path):
    run_dir = filled(tmp_path)
    rewrite_lines(run_dir / "manifest.jsonl", lambda lines: lines[:-1])
    with pytest.raises(RuntimeError, match="verify"):
        Recorder(run_dir)
