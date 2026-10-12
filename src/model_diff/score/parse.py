"""Turn a raw model response into a label.

Two levels of success are tracked separately:

- parse_ok: a valid label could be recovered from a JSON object anywhere in the
  response (code fences or surrounding prose are tolerated; label case is not
  significant). This is what accuracy is scored on.
- format_ok: the response is exactly one JSON object with only "label" and
  "rationale", and the label matches an allowed label exactly. A strict
  downstream parser would accept only these.

A response with no JSON object holding an allowed label is a parse failure;
bare-text answers such as "Yes" are not recovered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Parsed:
    label: str | None
    rationale: str | None
    parse_ok: bool
    format_ok: bool


def canonical_label(value: object, labels: list[str]) -> str | None:
    if not isinstance(value, str):
        return None
    key = value.strip().casefold()
    for label in labels:
        if label.casefold() == key:
            return label
    return None


def _first_labelled_object(text: str) -> dict | None:
    """The first JSON object in text that has a "label" key."""
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "label" in obj:
            return obj
    return None


def parse_response(text: str, labels: list[str]) -> Parsed:
    stripped = text.strip()
    try:
        whole = json.loads(stripped)
    except json.JSONDecodeError:
        whole = None

    obj = whole if isinstance(whole, dict) else _first_labelled_object(stripped)
    if obj is None:
        return Parsed(label=None, rationale=None, parse_ok=False, format_ok=False)

    label = canonical_label(obj.get("label"), labels)
    rationale = obj.get("rationale") if isinstance(obj.get("rationale"), str) else None
    format_ok = (
        isinstance(whole, dict)
        and set(whole) == {"label", "rationale"}
        and rationale is not None
        and whole.get("label") in labels
    )
    return Parsed(label=label, rationale=rationale, parse_ok=label is not None, format_ok=format_ok)
