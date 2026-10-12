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

## D12. Four arms and attribution of the headline change (2026-10-12, author request)

The run compares four arms built from the two pinned models:

| Arm | Model | Parameters |
|---|---|---|
| A | Sonnet 4.5 | temperature 0 |
| B | Sonnet 5.5 | API defaults: no temperature (1.0), default adaptive thinking, default effort |
| C | Sonnet 4.5 | temperature 1.0 |
| D | Sonnet 5.5 | temperature 1.0 (only accepted value), thinking off (`between_tools`) |

A vs B is the headline "real migration" comparison. The path A → C → D → B changes one factor per
step: temperature, then model, then thinking. For each case whose final answer differs between A
and B, the report lists which steps changed the answer. A factor *explains* a case alone when its
step is the only one that changed; it is *involved* when its step changed along with others. Each
step's disagreement rate is reported next to the arms' noise floors, because at temperature 1.0
some step-to-step change is sampling noise. This path is the only one available: Sonnet 5.5
cannot run at temperature 0, so the temperature step has to happen on Sonnet 4.5. Rejected:
order-averaged (Shapley-style) attribution, which needs arms that cannot exist here, such as
Sonnet 5.5 at temperature 0. Arm D is dropped first if the estimate exceeds the cap; without it,
only the combined model-and-thinking step (C → B) can be reported.

This supersedes D4's choice of turning thinking off for model B. That configuration is now arm D,
and the headline arm B uses the API defaults a migrating customer would get.

## D13. Arm B's max_tokens (2026-10-12)

`max_tokens` is required, so it has no API default. Adaptive thinking counts toward it, so arm B
uses 16,000 instead of the shared 512. Any arm-B response that still stops at `max_tokens` is
recorded with that stop reason and scored as a parse failure if no label survives.

## D14. Reweighting for unfair_tos (2026-10-12, author request)

`unfair_tos` keeps stratified sampling, so per-label precision and recall have support. Its flag
rate ("any unfair": any label except Other) is also reported post-stratified. The rate within each
gold label is weighted by that label's share of the full 3,813-clause test split, which
`model-diff sample` records in `data/cases.meta.json`. Accuracy is reweighted the same way. The
headline uses the pooled "any unfair" flag; per-category results are labelled exploratory. Pooled
all-task accuracy is computed over the sample as drawn and says so.

## D15. Judge model (2026-10-12, author request)

The judge is `claude-haiku-5-5`, replacing `claude-haiku-4-5-20251001` because of retirement risk.
On 2026-10-12 the models endpoint listed it as `active` and reported that thinking can be disabled.
It rejects non-default temperature, so judge calls omit `temperature` and send `thinking: disabled`
(accepted at its default effort, medium). Judge outputs are therefore not deterministic, so every
judge call is recorded and reused, never re-asked. Price: 0.10 / 0.50 USD per million input /
output tokens for prompts under 100K tokens.

## D16. Models-list snapshot (2026-10-12, author request)

Each run stores the full `GET /v1/models` response (active, deprecated, and retired models) as
`models_snapshot.json` in its run directory. Its SHA-256 is frozen in `run_config.json`, which is
the first link of the hash chain. On 2026-10-12 the endpoint reported Sonnet 4.5 as `active` with
no `deprecated_at` or `retires_at`. The Messages API reference lists it as deprecated, with end
of life on 2026-11-30.

## D17. Cost estimate and cap enforcement (2026-10-12)

The dry run counts input tokens exactly with the free token-counting endpoint, for each model.
Sonnet 5.5 counts 36% more tokens than Sonnet 4.5 for the same prompts. Output is planned at 100
visible tokens per call, plus 1,000 thinking tokens per call for arm B. Arm B's thinking length is
the main unknown: the estimate prints a sensitivity table and the thinking length at which the
cap is reached. The cap is applied to the expected total, judge ceiling included, and arms are
dropped in `drop_order` (D) until it fits.

Because the assumption could be wrong, the run enforces the cap with measurements:

1. One preflight call per arm with its exact parameters.
2. A pilot batch: 5% of each task's cases, every arm, every repeat.
3. A re-projection of the full run from the pilot's measured usage. If the projection exceeds the
   cap, arm D's remaining requests are dropped; if it still exceeds the cap, the run stops before
   any further spending.
4. The remaining batch, then the latency probes.

Rejected:

- A paid calibration call before the author approved the estimate.
- Capping arm B's `max_tokens` to bound the worst case. That would truncate thinking and corrupt
  the arm being measured.

## D18. Latency probes (2026-10-12)

Batch results carry no per-request latency. Latency is measured with sequential calls on the
first 10 cases of each task, for every arm, recorded as `kind: latency_probe`, billed at standard
rates, and excluded from accuracy.

## D19. Cost cap raised to 35 USD, pilot rule approved (2026-10-12, author decision)

The author approved the dry-run estimate (23.45 USD expected) and raised `cost_cap_usd` from 25 to
35 USD. The run executes the pilot first and re-projects the full run from the pilot's measured
usage. If the projection is at most 35 USD, all four arms run. If it is higher, arm D's remaining
requests are dropped. If it is still higher, the run stops before any further spending and asks
the author.

## D20. Attribution is labelled as sequential (2026-10-12, author decision)

The report calls the A → C → D → B breakdown "sequential attribution along the path A → C → D → B".
It states that factors can interact, so attributing along a different order of changes could split
the shares differently. The path order is fixed by what the API allows (D12), not chosen to favour
any factor.
