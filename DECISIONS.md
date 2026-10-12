# Decisions

Append-only. Each entry records a choice, why it was made, and what was rejected.

## D1. Package layout (2026-10-12)

Code lives in `src/model_diff/` with subpackages `data/`, `record/`, `score/`, `diff/`, and
`report/`, matching the brief's component names. Top-level `data/`, `prompts/`, and `runs/` hold
artifacts (the task proposal, prompt text, run outputs). Rejected: top-level importable packages
named `data`, `score`, `diff`, and `report`, which would install generic module names into
site-packages and collide with other projects.

## D2. Task selection rules (2026-10-12)

Only tasks whose LegalBench card states a license permitting commercial use (CC BY 4.0 or MIT)
are proposed, because the harness will later run commercially. Licenses are re-read from the
task cards at a pinned LegalBench commit every time `model-diff propose-tasks` runs. One
on-topic, permissively licensed candidate is excluded because its task identifier is a company
name; `data/tasks.yaml` refers to it only by the SHA-256 of that identifier. Rejected: proposing
non-commercial tasks with a usage caveat.

## D3. Stratified sampling for unfair_tos (2026-10-12)

91% of the `unfair_tos` test split is `Other`. A random draw of 200 would hold about two clauses
per unfair category, too few to measure anything about them. The task is sampled with equal shares
per gold label instead. Consequence: its flag rate describes the sample, not real terms of service.
The other tasks are sampled at random. Rejected: random sampling everywhere.

## D4. Model B cannot share model A's sampling parameters (2026-10-12)

Claude Sonnet 5.5 rejects any `temperature` other than the default 1.0 with a 400 error (Messages
API reference and Sonnet 5.5 migration guide, read 2026-10-12). The brief asks for temperature 0
"where the API allows", so model A runs at 0 and model B at the API default of 1.0. Both settings
are stored in every record's `params`. Model B also thinks before answering by default;
`thinking: {type: between_tools}` is its documented way to turn that off. That matches model A,
which does not think by default. The `n_runs` repeats measure the noise this leaves.

Rejected: (a) running both models at temperature 1.0, which ignores the brief's temperature 0
where it is possible; (b) leaving model B on default adaptive thinking, which compares a reasoning
configuration against a non-reasoning one. To separate the temperature effect from the model
effect, a control run can set `model_b` to model A's ID with `temperature: 1.0`.

## D5. No fallbacks, structured outputs, or prefill (2026-10-12)

Server-side refusal fallback would let another model answer inside a run, breaking the pinned
model ID, and the Batches API rejects it. Structured outputs would guarantee valid JSON and hide
the format drift this harness exists to measure. Assistant prefill returns a 400 on Sonnet 5.5.
Refusals are recorded as refusals.

## D6. Two parse levels (2026-10-12)

`parse_ok`: a JSON object somewhere in the response holds an allowed label, ignoring case;
accuracy is scored on this. `format_ok`: the response is exactly one JSON object with only
`label` and `rationale`, and the label matches exactly; this is what a strict downstream parser
would accept. A bare-text answer such as `Yes` is a parse failure. Rejected: recovering bare-text
labels, which would hide format drift in the accuracy numbers.

## D7. Majority vote and noise floor (2026-10-12)

Each repeat yields one outcome: a label, `<REFUSAL>`, or `<PARSE_FAIL>`. The final answer is the
most frequent outcome; a tie goes to the tied outcome from the earliest repeat. Refusals and parse
failures can win and always count as wrong. The noise floor is 1 minus the mean pairwise agreement
between a model's repeats (the chance two runs of one model disagree on a case). It is reported
next to the cross-model disagreement between single runs of A and B. Unanimity is also reported.

## D8. Diff precedence (2026-10-12)

`refusal_change` (exactly one side refused), then `format_drift` (exactly one side unparseable,
or the same label where one model's repeats mostly broke the strict format), then comparison
against gold. Rejected: counting a same-label strict-format break as `same`, which would hide
format changes that break downstream parsers.

## D9. API key handling (2026-10-12)

The harness reads `ANTHROPIC_API_KEY` from `.env` (gitignored), and `.env` takes precedence over
the process environment, so a key exported for another tool cannot bill this harness. The key is
never printed or recorded.

## D10. Startup model check (2026-10-12)

Commands that call the API first list the account's models and confirm all three pinned IDs. If
model A is missing they exit with a clear message. Offline commands (`verify`, `report`) skip
the check, so a run stays verifiable after model A is retired. On 2026-10-12 the models list
reported `claude-sonnet-4-5-20250929` as `active` with no `retires_at`, while the Messages API
reference lists it as deprecated with end of life on 2026-11-30. Both facts are recorded.

## D11. Scope of "no company names" (2026-10-12)

The repository names no customers, employers, or companies drawn from the data. It does name the
model provider, the dataset host, and the code host (needed to cite the SDK, the models, and the
data sources the brief itself names). Text quoted from public datasets can mention companies
(for example, website names in terms-of-service clauses), so sampled cases and run outputs are
gitignored. A screened-out task whose identifier is a company name is referenced by hash only.
