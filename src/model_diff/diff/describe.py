"""Judge descriptions of each headline change: its nature in one category and one sentence."""

from __future__ import annotations

from ..data.cases import Case
from ..data.tasks import TaskSpec
from ..prompts import format_labels
from .differ import DiffRow

NATURES = ("stricter", "more_lenient", "misread_instruction", "format_change", "other")


def judge_prompt(row: DiffRow, case: Case, spec: TaskSpec) -> str:
    return "\n".join(
        [
            f"Task: {row.task} ({spec.domain}). Allowed labels: {format_labels(spec.labels)}.",
            "",
            "Input:",
            "<<<",
            case.input,
            ">>>",
            "",
            f"Reference label: {row.gold}",
            "",
            f"Model A final answer: {row.a_answer} (repeats: {row.a_votes})",
            "Model A response:",
            "<<<",
            row.a_response,
            ">>>",
            "",
            f"Model B final answer: {row.b_answer} (repeats: {row.b_votes})",
            "Model B response:",
            "<<<",
            row.b_response,
            ">>>",
        ]
    )


def describe(rows: list[DiffRow], cases: dict[str, Case], tasks: dict[str, TaskSpec], judge, pair: tuple[str, str]) -> None:
    """Fill judge_nature and judge_sentence on every row whose category is not "same"."""
    for row in rows:
        if row.category == "same":
            continue
        ref = f"{pair[0]}>{pair[1]}|{row.case_id}"
        verdict = judge.ask("judge_diff", ref, row.case_id, row.task, 0, judge_prompt(row, cases[row.case_id], tasks[row.task]))
        if verdict is None:
            # The judge answered but not in valid JSON, or it was never asked (budget spent, no client).
            answered = ("judge_diff", ref) in judge.recorded
            row.judge_nature, row.judge_sentence = ("judge_unparseable" if answered else "not_judged"), ""
            continue
        nature = verdict.get("nature")
        row.judge_nature = nature if nature in NATURES else "unparsed"
        row.judge_sentence = str(verdict.get("sentence", "")).strip()
