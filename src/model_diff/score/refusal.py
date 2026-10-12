"""Refusal detection: the API's own refusal signal, a small rule set, and the judge.

- A response with stop_reason "refusal" is a refusal (source "api").
- Otherwise a response is a candidate if it could not be parsed or its text
  matches a refusal rule. The judge decides each candidate (source "judge").
  If the judge is unavailable, over budget, or unparseable, the rule decides
  (source "rule").
- Every other response attempted the classification and is not a refusal.
"""

from __future__ import annotations

import re

from ..prompts import format_labels
from ..record.schema import CallRecord

REFUSAL_RULES = re.compile(
    r"\bI (?:can(?:no|')t|cannot|won't|will not|am unable to|'m unable to|am not able to|'m not able to)\b"
    r"|\bunable to (?:provide|assist|help|classify|determine)\b"
    r"|\b(?:not|never) (?:provide|give|offer)(?:ing)? legal advice\b"
    r"|\b(?:consult|speak with|contact) (?:a|an) (?:qualified |licensed )?(?:attorney|lawyer|legal professional)\b"
    r"|\bI (?:must|have to) decline\b",
    re.IGNORECASE,
)


def rule_hit(text: str) -> bool:
    return bool(REFUSAL_RULES.search(text))


def is_candidate(rec: CallRecord) -> bool:
    return rec.stop_reason != "refusal" and (not rec.parse_ok or rule_hit(rec.raw_response))


def judge_prompt(rec: CallRecord, labels: list[str]) -> str:
    return f"Allowed labels: {format_labels(labels)}\n\nResponse:\n<<<\n{rec.raw_response}\n>>>"


def refusal_decisions(records: list[CallRecord], labels: dict[str, list[str]], judge=None) -> dict[str, dict]:
    """Refusal decision and its source for every subject call that needed one."""
    decisions: dict[str, dict] = {}
    for rec in records:
        if rec.kind != "subject" or rec.error is not None:
            continue
        key = rec.subject_key()
        if rec.stop_reason == "refusal":
            decisions[key] = {"refusal": True, "source": "api"}
        elif is_candidate(rec):
            verdict = None
            if judge is not None:
                verdict = judge.ask("judge_refusal", key, rec.case_id, rec.task, rec.repeat_index, judge_prompt(rec, labels[rec.task]))
            if verdict is not None and isinstance(verdict.get("refusal"), bool):
                decisions[key] = {"refusal": verdict["refusal"], "source": "judge"}
            else:
                decisions[key] = {"refusal": rule_hit(rec.raw_response), "source": "rule"}
    return decisions
