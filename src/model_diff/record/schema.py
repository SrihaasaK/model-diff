"""The call record: one line of runs/<run_id>/calls.jsonl per model invocation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

JUDGE = "judge"

# subject:        a scored classification call (batch or sequential)
# latency_probe:  a sequential repeat of a subject request, used only for latency
# preflight:      a minimal request validating each arm's parameters before the batch
# judge_refusal:  the judge deciding whether a candidate response is a refusal
# judge_diff:     the judge describing how the candidate arm's answer differs from the baseline's
Kind = Literal["subject", "latency_probe", "preflight", "judge_refusal", "judge_diff"]


class CallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Fields required by the spec.
    run_id: str
    case_id: str
    task: str
    model_id: str
    params: dict[str, Any]
    prompt_sha256: str
    request_id: str | None  # request-id header for direct calls; batch results carry message_id instead
    raw_response: str  # the response's text blocks, joined; thinking blocks are not included
    parsed_label: str | None
    parse_ok: bool
    input_tokens: int
    output_tokens: int  # billed output, including any thinking tokens
    latency_ms: float | None  # None for batch results, which have no per-request latency
    timestamp: str  # ISO 8601 UTC, when the response was recorded
    sdk_version: str
    repeat_index: int

    # Context needed to score and audit the record.
    arm: str  # an arm name from config.yaml, or "judge"
    kind: Kind
    format_ok: bool = False  # exactly one JSON object with only "label" and "rationale"
    thinking_tokens: int | None = None  # the part of output_tokens spent thinking, when reported
    stop_reason: str | None = None
    stop_details: dict[str, Any] | None = None
    message_id: str | None = None
    response_model: str | None = None
    batch_id: str | None = None
    custom_id: str | None = None
    subject_ref: str | None = None  # for judge records: the subject call or case being judged
    error: str | None = None  # set when the call failed permanently; such records are never scored

    def subject_key(self) -> str:
        """Identifies one subject call within a run: arm, case, repeat."""
        return subject_key(self.arm, self.case_id, self.repeat_index)


def subject_key(arm: str, case_id: str, repeat_index: int) -> str:
    return f"{arm}|{case_id}|{repeat_index}"
