"""Judge-vs-human agreement on the review sample, and how the reference labels were made."""

from __future__ import annotations

from collections import defaultdict

METHOD = (
    "Reference labels are a rule-based first pass by the harness author's agent, not blind to the judge's labels, "
    "confirmed against a reviewer rule table, with disputed rows resolved individually by the author."
)

# The author's direction rule, verbatim.
DIRECTION_RULE = [
    '"stricter" = Sonnet 5.5 is more likely than 4.5 to flag, deny, find a violation, or require more before '
    'accepting. "more_lenient" = the reverse.',
    "A move TO Ambiguous FROM Yes/Covered/Entailment is stricter; TO Ambiguous FROM No/Not covered/Contradiction is "
    "more_lenient. Apply this consistently; it resolves the judge's conflict on rows 2 and 10.",
    '"misread_instruction" only when 5.5 answered a different question than the one asked (check the input, not the '
    "judge's sentence).",
    '"format_change" for same-label rows where only the code fence, whitespace or JSON shape differs.',
    '"other" for category choices on multi-category tasks (unfair_tos categories) and for same-label rows with minor '
    "reasoning differences; put the reason in rule_note.",
]

# How the rule is read on tasks where its clauses point different ways (author decision); rendered in the report's
# method only for tasks the run includes.
DIRECTION_READINGS = {
    "privacy_policy_qa": 'On `privacy_policy_qa`, the direction rule is read as "more likely to mark Relevant = '
    'more_lenient," since "more flags" and "requires more before accepting" diverge on relevance tasks.',
}


def label_reading(per_label: dict[str, dict[str, int]], unreliable: list[str], held: list[str]) -> dict:
    """The author's reading of which judge labels to trust, refused where the counts contradict it."""
    for label in [*unreliable, *held]:
        if label not in per_label:
            raise ValueError(f"{label!r} is not a judge label in the review sample")
    for label in unreliable:
        v = per_label[label]
        if 2 * v["agree"] >= v["n"]:
            raise ValueError(f"{label!r} matched {v['agree']} of {v['n']}; that does not support calling it unreliable")
    for label in held:
        v = per_label[label]
        if 2 * v["agree"] <= v["n"]:
            raise ValueError(f"{label!r} matched {v['agree']} of {v['n']}; that does not support saying it held")
    return {"unreliable": list(unreliable), "held": list(held)}


def agreement(rows: list[dict]) -> dict:
    """Agreement between the judge's label and the confirmed human label, overall and per judge label."""
    reviewed = [r for r in rows if r["human_verdict"]]
    agree = [r for r in reviewed if r["judge_nature"] == r["human_verdict"]]
    judged = [r for r in reviewed if r["judge_nature"] not in ("judge_unparseable", "not_judged")]
    per_label: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "agree": 0})
    for r in reviewed:
        per_label[r["judge_nature"]]["n"] += 1
        per_label[r["judge_nature"]]["agree"] += r["judge_nature"] == r["human_verdict"]
    return {
        "n": len(rows),
        "n_reviewed": len(reviewed),
        "agree": len(agree),
        "agreement": len(agree) / len(reviewed) if reviewed else None,
        "n_judged": len(judged),
        "agreement_judged": sum(r["judge_nature"] == r["human_verdict"] for r in judged) / len(judged) if judged else None,
        "per_judge_label": dict(sorted(per_label.items())),
        "disagreements": [
            {k: r[k] for k in ("row", "case_id", "task", "category", "judge_nature", "human_verdict", "notes")}
            for r in reviewed
            if r["judge_nature"] != r["human_verdict"]
        ],
        "judge_overridden": len(reviewed) - len(agree),
        "rule_overridden": sum(r["rule_label"] != r["human_verdict"] for r in reviewed),
    }
