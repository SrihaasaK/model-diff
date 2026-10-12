"""Anthropic client construction, the startup model check, and retrying calls."""

from __future__ import annotations

import datetime as dt
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


SAMPLING_KEYS = ("temperature", "top_p", "top_k")


def sdk_kwargs(request: dict) -> dict:
    """Keyword arguments for messages.create() that send exactly this request.

    The 1.x SDK removed the sampling parameters from messages.create(), but the
    API still honours them on models that accept them (Sonnet 4.5 among them),
    so they travel in extra_body, which is merged into the request JSON as is.
    Batch requests need no change: the SDK forwards their params dict as given.
    """
    kwargs = {k: v for k, v in request.items() if k not in SAMPLING_KEYS}
    sampling = {k: request[k] for k in SAMPLING_KEYS if k in request}
    if sampling:
        kwargs["extra_body"] = sampling
    return kwargs


@dataclass(frozen=True)
class ModelStatus:
    role: str
    id: str
    display_name: str
    lifecycle: str
    retires_at: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def list_models(client: anthropic.Anthropic) -> list:
    """Every model the API reports for this key, including deprecated and retired ones."""
    return with_backoff(
        lambda: list(client.models.list(lifecycle=["active", "deprecated", "retired"], limit=1000))
    )


def models_snapshot(listed: list) -> dict:
    """The models-list response as JSON, for storing beside run outputs."""
    return {
        "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "endpoint": "GET /v1/models?lifecycle=active,deprecated,retired",
        "models": [m.model_dump(mode="json") for m in listed],
    }


def check_models(listed: list, cfg: Config, echo: Callable[[str], None] = print) -> list[ModelStatus]:
    """Confirm every pinned ID is listed and not retired, and print each one's status.

    Exits with a clear message if model_a (the model being retired) is gone,
    or if model_b or the judge is missing.
    """
    by_id = {m.id: m for m in listed if m.lifecycle != "retired"}
    pinned = [("model_a", cfg.model_a), ("model_b", cfg.model_b), ("judge_model", cfg.judge_model)]
    statuses: list[ModelStatus] = []
    for role, model_id in pinned:
        info = by_id.get(model_id)
        if info is None:
            if role == "model_a":
                raise SystemExit(
                    f"model_a '{model_id}' is not available to this API key. It may have been "
                    "retired (Claude Sonnet 4.5 reaches end of life on 2026-11-30) or the ID is "
                    "wrong. The comparison cannot run without it; existing runs can still be "
                    "scored, reported, and verified offline."
                )
            raise SystemExit(f"{role} '{model_id}' is not available (not listed, or retired) for this API key.")
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
