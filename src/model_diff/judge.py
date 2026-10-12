"""Judge calls, recorded in the run's hash chain and reused rather than re-asked.

The judge cannot be made deterministic (Haiku 5.5 rejects non-default
temperature), so each question is asked at most once per run: a later score or
diff reads the recorded answer. Judge spend is capped by judge.budget_usd;
once it is reached, callers fall back to their rule-based answers.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import anthropic

from .api import with_backoff
from .config import Config
from .prompts import prompt_sha256
from .record.recorder import Recorder
from .record.schema import JUDGE, CallRecord
from .runner import response_text, thinking_tokens, utc_now


def parse_json_object(text: str) -> dict | None:
    """The response as a JSON object, or the first JSON object inside it."""
    stripped = text.strip()
    try:
        whole = json.loads(stripped)
        return whole if isinstance(whole, dict) else None
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for start, char in enumerate(stripped):
        if char == "{":
            try:
                obj, _ = decoder.raw_decode(stripped, start)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


class Judge:
    def __init__(self, cfg: Config, client: Any | None, recorder: Recorder, prompts_dir: Path,
                 echo: Callable[[str], None] = print):
        self.cfg = cfg
        self.client = client
        self.recorder = recorder
        self.prompts_dir = prompts_dir
        self.echo = echo
        self.params = cfg.judge_params()
        self.recorded = {
            (r.kind, r.subject_ref): r for r in recorder.records if r.arm == JUDGE and r.error is None
        }
        self.spent = sum(self.cost(r) for r in recorder.records if r.arm == JUDGE)
        self.asked = 0
        self.skipped = 0

    def cost(self, rec: CallRecord) -> float:
        return self.cfg.cost_usd(rec.model_id, rec.input_tokens, rec.output_tokens, batch=False)

    def system(self, kind: str) -> str:
        return (self.prompts_dir / f"{kind}.txt").read_text(encoding="utf-8").strip()

    def ask(self, kind: str, subject_ref: str, case_id: str, task: str, repeat_index: int, user_text: str) -> dict | None:
        """The judge's JSON answer for this item: recorded if asked before, else asked now.

        Returns None when the answer is unparseable, the budget is spent, or no client is available.
        """
        rec = self.recorded.get((kind, subject_ref))
        if rec is None:
            if self.client is None or self.spent >= self.cfg.judge.budget_usd:
                self.skipped += 1
                return None
            system = self.system(kind)
            messages = [{"role": "user", "content": user_text}]
            request = {**self.params, "system": system, "messages": messages}
            start = time.perf_counter()
            try:
                message = with_backoff(lambda: self.client.messages.create(**request), echo=self.echo)
            except anthropic.APIError as exc:
                self.echo(f"  judge call failed for {subject_ref}: {type(exc).__name__}")
                self.skipped += 1
                return None
            latency = (time.perf_counter() - start) * 1000
            text = response_text(message)
            rec = CallRecord(
                run_id=self.recorder.run_id, case_id=case_id, task=task, model_id=self.params["model"],
                params=self.params, prompt_sha256=prompt_sha256(system, messages),
                request_id=getattr(message, "_request_id", None), raw_response=text, parsed_label=None,
                parse_ok=parse_json_object(text) is not None, input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens, latency_ms=latency, timestamp=utc_now(),
                sdk_version=anthropic.__version__, repeat_index=repeat_index, arm=JUDGE, kind=kind,
                thinking_tokens=thinking_tokens(message), stop_reason=message.stop_reason,
                message_id=message.id, response_model=message.model, subject_ref=subject_ref,
            )
            self.recorder.append(rec)
            self.recorded[(kind, subject_ref)] = rec
            self.spent += self.cost(rec)
            self.asked += 1
        return parse_json_object(rec.raw_response)
