"""Anthropic client construction, the startup model check, and retrying calls."""

from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass
from typing import Callable, TypeVar

import anthropic

from .config import Config
from .env import load_api_key

T = TypeVar("T")


def make_client() -> anthropic.Anthropic:
    """A client with SDK retries off; with_backoff() owns the retry policy."""
    return anthropic.Anthropic(api_key=load_api_key(), max_retries=0)


@dataclass(frozen=True)
class ModelStatus:
    role: str
    id: str
    display_name: str
    lifecycle: str
    retires_at: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def check_models(client: anthropic.Anthropic, cfg: Config, echo: Callable[[str], None] = print) -> list[ModelStatus]:
    """List the account's models and confirm every pinned ID is callable.

    Exits with a clear message if model_a (the model being retired) is gone,
    or if model_b or the judge is missing.
    """
    listed = {
        m.id: m
        for m in with_backoff(lambda: list(client.models.list(lifecycle=["active", "deprecated"], limit=1000)))
    }
    pinned = [("model_a", cfg.model_a), ("model_b", cfg.model_b), ("judge_model", cfg.judge_model)]
    statuses: list[ModelStatus] = []
    for role, model_id in pinned:
        info = listed.get(model_id)
        if info is None:
            if role == "model_a":
                raise SystemExit(
                    f"model_a '{model_id}' is not available to this API key. It may have been "
                    "retired (Claude Sonnet 4.5 reaches end of life on 2026-11-30) or the ID is "
                    "wrong. The comparison cannot run without it; existing runs can still be "
                    "scored, reported, and verified offline."
                )
            raise SystemExit(f"{role} '{model_id}' is not in the models list for this API key.")
        retires = info.retires_at.date().isoformat() if info.retires_at else None
        statuses.append(ModelStatus(role, model_id, info.display_name, info.lifecycle, retires))
    for s in statuses:
        note = f"retires {s.retires_at}" if s.retires_at else ""
        echo(f"  {s.role:<12} {s.id:<30} {s.display_name:<20} {s.lifecycle:<11} {note}".rstrip())
    return statuses


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (408, 409, 429) or exc.status_code >= 500
    return False


def _retry_after_seconds(exc: Exception) -> float | None:
    if isinstance(exc, anthropic.APIStatusError):
        value = exc.response.headers.get("retry-after")
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None
    return None


def with_backoff(
    fn: Callable[[], T],
    *,
    max_attempts: int = 6,
    base_delay: float = 2.0,
    max_delay: float = 120.0,
    sleep: Callable[[float], None] = time.sleep,
    echo: Callable[[str], None] = print,
) -> T:
    """Call fn, retrying rate limits, overloads, 5xx, and connection errors.

    Delays grow 2, 4, 8, ... seconds (plus up to 1s jitter, capped at
    max_delay) unless the server sends retry-after. Other errors raise at once.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except anthropic.APIError as exc:
            if not is_retryable(exc) or attempt == max_attempts:
                raise
            delay = _retry_after_seconds(exc)
            if delay is None:
                delay = min(max_delay, base_delay * 2 ** (attempt - 1)) + random.uniform(0, 1)
            echo(f"    retry {attempt}/{max_attempts - 1} in {delay:.1f}s after {type(exc).__name__}")
            sleep(delay)
    raise AssertionError("unreachable")
