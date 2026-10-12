import pytest

from model_diff.score.parse import parse_response

LABELS = ["Yes", "No", "Ambiguous"]


@pytest.mark.parametrize(
    ("raw", "label", "parse_ok", "format_ok"),
    [
        ('{"label": "Yes", "rationale": "Covered."}', "Yes", True, True),
        ('  {"label": "No", "rationale": "x"}\n', "No", True, True),
        ('```json\n{"label": "No", "rationale": "x"}\n```', "No", True, False),
        ('Answer: {"label": "Ambiguous", "rationale": "x"} Done.', "Ambiguous", True, False),
        ('{"note": "x"} {"label": "No", "rationale": "y"}', "No", True, False),
        ('{"label": "yes", "rationale": "x"}', "Yes", True, False),
        ('{"label": "Yes", "rationale": "x", "confidence": 0.9}', "Yes", True, False),
        ('{"label": "Yes"}', "Yes", True, False),
        ('{"label": "Maybe", "rationale": "x"}', None, False, False),
        ('{"label": ["Yes"], "rationale": "x"}', None, False, False),
        ("Yes", None, False, False),
        ("", None, False, False),
        ('{"label": "Yes", "rationale": "truncated by max_tok', None, False, False),
    ],
)
def test_parse_response(raw, label, parse_ok, format_ok):
    parsed = parse_response(raw, LABELS)
    assert (parsed.label, parsed.parse_ok, parsed.format_ok) == (label, parse_ok, format_ok)


def test_rationale_is_returned_when_present():
    assert parse_response('{"label": "No", "rationale": "Excluded peril."}', LABELS).rationale == "Excluded peril."
    assert parse_response('{"label": "No", "rationale": 3}', LABELS).rationale is None
