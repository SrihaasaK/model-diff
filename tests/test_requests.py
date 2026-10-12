from pathlib import Path

from model_diff.config import load_config
from model_diff.data.cases import Case
from model_diff.data.tasks import load_tasks
from model_diff.prompts import PLACEHOLDER, PromptBook, format_labels

REPO = Path(__file__).resolve().parents[1]


def book():
    tasks = load_tasks(REPO / "data" / "tasks.yaml").tasks
    return PromptBook(REPO / "prompts", tasks), tasks


def test_format_labels():
    assert format_labels(["Yes", "No"]) == '"Yes" or "No"'
    assert format_labels(["Yes", "No", "Ambiguous"]) == '"Yes", "No", or "Ambiguous"'


def test_every_task_prompt_lists_its_labels_and_asks_for_json_only():
    prompts, tasks = book()
    for task, spec in tasks.items():
        system = prompts.systems[task]
        assert PLACEHOLDER not in system
        assert all(f'"{label}"' in system for label in spec.labels)
        assert '"label"' in system and '"rationale"' in system and "only a JSON object" in system


def test_arms_receive_identical_prompts_and_differ_only_in_parameters():
    prompts, _ = book()
    case = Case(case_id="x", task="telemarketing_sales_rule", input="Facts:\nA seller called.", gold_label="Yes", license="CC BY 4.0")
    request_a, sha_a = prompts.request(case, {"model": "m1", "temperature": 0})
    request_b, sha_b = prompts.request(case, {"model": "m2", "max_tokens": 16000})
    assert sha_a == sha_b
    assert (request_a["system"], request_a["messages"]) == (request_b["system"], request_b["messages"])
    assert request_a["messages"] == [{"role": "user", "content": case.input}]


def test_prompt_digest_covers_task_and_judge_prompts():
    prompts, tasks = book()
    digest = prompts.digest()
    assert {f"{spec.family}.txt" for spec in tasks.values()} <= set(digest)
    assert {"judge_refusal.txt", "judge_diff.txt"} <= set(digest)


def test_config_builds_each_arms_exact_parameters():
    cfg = load_config(REPO / "config.yaml")
    assert cfg.arm_params("A") == {"model": cfg.model_a, "max_tokens": 512, "temperature": 0}
    assert cfg.arm_params("B") == {"model": cfg.model_b, "max_tokens": 16000}
    assert cfg.arm_params("C") == {"model": cfg.model_a, "max_tokens": 512, "temperature": 1.0}
    assert cfg.arm_params("D") == {"model": cfg.model_b, "max_tokens": 512, "thinking": {"type": "between_tools"}}
    assert cfg.judge_params() == {"model": cfg.judge_model, "max_tokens": 300, "thinking": {"type": "disabled"}}
    assert cfg.pinned_model_ids() == {cfg.model_a, cfg.model_b, cfg.judge_model}
