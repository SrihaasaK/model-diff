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

## D21. How refusals are decided (2026-10-12)

1. A response whose `stop_reason` is `refusal` is a refusal, as the API itself declined.
2. Any other response becomes a candidate if it cannot be parsed or matches a small rule set.
   The rules cover phrases such as "I can't", "unable to provide", "not legal advice", and
   "consult an attorney". The judge decides each candidate.
3. If the judge is over budget, unavailable, or unparseable, the rule decides. Each decision
   records its source (`api`, `judge`, or `rule`) in `refusals.json`.
4. Every other response attempted the classification. Judge answers are recorded in the run's
   hash chain and reused on later scoring, never re-asked.

Rejected: rules alone, which miss polite deflections; asking the judge about every response,
which costs more and adds judge noise to clean answers.

## D22. Run-time safeguards added after an independent review (2026-10-12)

A reviewer subagent audited the runner before any spend. Nothing critical was found; these fixes
followed.

- A batch's intent is saved before the create call, and the create is never retried blindly. If
  creation fails or was interrupted, a batch created since the intent with the same request count
  is adopted instead of resubmitted. This prevents double billing.
- Before every batch and every direct call, recorded spend plus the estimated new work plus the
  judge reserve must fit the cap. Direct work is priced at the standard rate.
- A cap stop keeps the run's phase, so the run can be resumed after the cap is raised.
- Resuming requires a verified chain and an unchanged job-defining config. Only the cost cap,
  the judge budget, the poll interval, and paths may change.
- An append cut short by a crash is set aside to `orphans.jsonl`, outside the chain, and its
  request is re-sent.
- A response from an unpinned model stops the run with an explicit reason.
- One process at a time may run a given run directory.

Rejected: a safety margin on the pilot projection. The author's rule is "projects at most 35
USD", and the per-call guard is the backstop.

## D23. Sending temperature with the 1.x SDK (2026-10-12)

`anthropic` 1.x removed `temperature` from `messages.create()`. The API still accepts it for
Sonnet 4.5. Direct calls therefore send it in `extra_body`, and batch requests keep it in each
request's `params`, which the SDK forwards as given. Wire-level tests use the real SDK on a mock
transport to show that `temperature` reaches the request body on both paths.

The first launch failed client-side with a `TypeError` before any API call: no spend, and an empty
run directory `runs/20261012T222724Z` left in place. The run reported on is `20261012T222853Z`.

## D24. Pilot measurements (2026-10-12)

The pilot measured these per-call means:

| Arm | Input tokens | Output tokens | Thinking tokens |
|---|---|---|---|
| A | 304 | 64 | none |
| B | 417 | 235 | 105 |
| C | 304 | 66 | none |
| D | 416 | 116 | 0 |

Arm B's thinking came to 105 tokens per call, against the 1,000-token planning assumption. The
re-projected total was 11.80 USD against the 35 USD cap, so all four arms continued. The
assumption is kept in config as written; it was a planning number, and the pilot replaced it as
designed.

## D25. Report changes made after reading the results (2026-10-12)

These changes were made after the run's results were read. Each adds disclosure; none changes a
category, metric, sample, or number.

- **Format-drift split.** All 420 `format_drift` cases kept the same label. In 401 of them, arm
  A's repeats mostly broke the strict JSON format and B's did not. The report now says so, and
  shows how each arm missed the format: arm A wrapped valid JSON in a Markdown code fence on
  1,591 calls, and arm B put text before the JSON on 297.
- **Output-limit caveat.** 24 calls stopped at the 512-token limit (A 1, C 1, D 22), all on
  `sara_entailment` and all before a parseable label, because reasoning was written into the
  visible answer. The report states this; nothing was re-run.
- **Unparseable judge answers.** Five judge descriptions were invalid JSON (four had unescaped
  quotes, and one hit the 300-token judge limit). They are now labelled `judge_unparseable`
  instead of `not_judged`.
- **Chart annotations.** The diff chart labels each bar with its label changes and its
  format-only changes separately, and drops numbers that do not fit their segment.
- **Published copy.** `reports/<run_id>/` holds text-free copies for publication: the report,
  charts, metrics, diff summary, run config, models snapshot, and head. The full run directory
  quotes source text and stays local.

Rejected: redefining `format_drift` to exclude same-label cases now that it dominates the
counts. That would change a category fixed in D8 after seeing the results. Re-drawing the review
sample with equal shares per category, so that label changes outnumber format-only ones, is left
to the author.

## D26. The model-only comparison and why its parameters differ (2026-10-12, author request)

The report's primary comparison is arm C (Sonnet 4.5) against arm D (Sonnet 5.5). This is the
step on the attribution path whose intended difference is the model. Both arms get identical
prompts and run at temperature 1.0, without thinking, with a 512-token output limit. Their
request parameters are not byte-identical:

- Arm C sends `temperature: 1.0`. Arm D sends no temperature, so Sonnet 5.5 uses its API default
  of 1.0, the only value it accepts.
- Arm D sends `thinking: {type: between_tools}`, Sonnet 5.5's documented way to turn off
  up-front thinking. Sonnet 4.5 does not think unless asked, so arm C sends nothing.

Each difference expresses the same intended setting in the form each model accepts. The report
lists the differences rather than calling the settings identical.

Two consequences:

- 5 of arm D's final answers on `sara_entailment` are unparseable. Its reasoning, written into
  the visible answer, ran past 512 tokens. These count as wrong for Sonnet 5.5, so they understate
  it in the model-only comparison.
- The next step on the path (D → B) changes thinking and also raises `max_tokens` from 512 to
  16,000. The attribution table lists both.

## D27. Direction of change per task (2026-10-12)

A changed answer (model-only pair) moves toward the flag when Sonnet 5.5 gives a flag label and
Sonnet 4.5 did not, and away in the reverse case. Changes between two flag labels, between two
non-flag labels, or with no label on one side are counted separately. A task is called "more
flags" or "fewer flags" when at least 5 changes cross the flag boundary and at least two thirds
cross it the same way. Otherwise it is "mixed", or "too few changes to call" below 5.

"Stricter" and "more lenient" are used only where a flag is an adverse finding. This is recorded
as `stricter_when` in `data/tasks.yaml`, added after the run. It is a reading of the task and
changes no number:

- `telemarketing_sales_rule` and `unfair_tos`: more flags is stricter.
- `insurance_policy_interpretation`: fewer claims judged covered is stricter.
- `privacy_policy_qa` and `sara_entailment`: a flag is not adverse, so the raw direction is
  reported.

The thresholds were set before the per-task directions were read. Rejected: judge natures as the
direction, because they exist only for the A-vs-B pair.

## D28. Review sample: equal shares, model-only pair, no judge descriptions (2026-10-12, author request)

`diffs_sample_for_review.csv` is redrawn from the model-only pair with up to 6 cases per change
category. Spare slots go round-robin to categories that have rows left, and unchanged cases are
never added. `refusal_change` is empty in this run, so its 6 slots were redistributed.

The judge described changes only for the A-vs-B pair, and this step makes no new API calls. The
sampled rows therefore have `judge_nature: not_judged`. Measuring judge-vs-human agreement on
this sample needs either judge calls for these 30 cases or a different comparison; that is the
author's decision.

## D29. Latency out of the tables; offline mode; publish set (2026-10-12, author request)

- Mean latency is dropped from every report table. It is still in `scores.json`, and probe spend
  stays in the cost table.
- `score --offline` and `diff --offline` make no API call. They reuse recorded judge answers, and
  rules decide anything unrecorded.
- `model-diff publish` copies only aggregate files (report, per-task and attribution tables,
  charts, scores, diff summary, run config, models snapshot, head) to `reports/<run_id>/`, with a
  README holding the chain head and the `verify` command.

## D30. Judge descriptions for the model-only review sample (2026-10-12, author decision)

The author authorized one judge pass on the 30 sampled model-only changes, choosing option 1 at
the review stop point. `model-diff describe-sample` asked `claude-haiku-5-5` once per sampled
case, using the same prompt as the A-vs-B descriptions, for 0.0039 USD. The 30 calls are recorded
in the run's hash chain with `subject_ref` `C>D|<case_id>`. The chain now holds 10,152 records,
and the head moved from `b718cc49…03ba3` to `142a627c…f1c151`.

No other model-only change was judged. `diff --offline` fills recorded descriptions only, and
`write_review_sample` keeps any `human_verdict` and `notes` already entered when the sample file is
rewritten. One judge answer was not valid JSON and is labelled `judge_unparseable`.

The judge's sentences quote case text, including people's names and a product name. They stay in
the gitignored run directory.

## D31. Judge reliability: how the reference labels were made (2026-10-12, author decisions)

The judge's `nature` label on the 30 model-only review rows is compared with a reference label.
The reference labels are not independent human labels, and the report never calls them that.
They were made in three steps:

1. The harness author's agent wrote a rule-based first pass (`rule_label`, `rule_note`) by applying
   the author's direction rule. The rule is stored verbatim in `score/reliability.py` and printed
   verbatim in the report. The agent had already seen the judge's labels, so the first pass is
   not blind to them.
2. The author confirmed row 1 individually, then confirmed rows 2–30 in batch against a reviewer
   rule table of expected labels (`review_rule_table.json`, in the run directory).
3. Rows that disagreed with the table, plus rows 6 and 8, were printed in full and the author
   resolved each one individually.

The method sentence in the report says exactly this.

Result, recomputed by `model-diff reliability` from the review file:
- The judge matched the reference on 23 of 30 rows (76.7%), and on 23 of the 29 rows where its
  answer parsed (79.3%).
- The reference differs from the judge on 7 rows. The author's review changed 5 of the agent's
  first-pass labels (rows 6, 14, 21, 23 and 28).
- The judge's `misread_instruction` label matched in 0 of 3 uses. On this sample, read it as a
  weak signal.

The report gives raw agreement with a per-judge-label table and lists every disagreement with
its reviewer note. A chance-corrected statistic was rejected: with 30 rows spread over six labels,
it would be unstable, and the full table carries more information.

The report's first draft said "the author overrode 7 judge labels". That wording was corrected
before publishing, because some of those 7 reference labels came from the rule table rather than
from an individual ruling.

The author added a differ caveat, now in the report: same-label rows 25, 28 and 29 carry minor
reasoning differences that the differ does not detect, so `format_drift` slightly understates
substantive change.

Rejected alternative: a blind relabel by a second reviewer. It would be the stronger design, but
no second reviewer was available here; the caveat stands in its place.

## D32. `examples.md`: three vetted examples (2026-10-12, author request)

All three examples are `privacy_policy_qa` cases from the model-only review sample, so each has
both a judge label and a reference label:
- Example 1 (`-04433`): Sonnet 4.5 right, Sonnet 5.5 wrong.
- Example 2 (`-01104`): the opposite direction on the same task.
- Example 3 (`-09917`): `format_drift`.

The text says that examples 1 and 2 are a 2-against-13 pair on that task, not an even split, so
the pair does not suggest the task has no direction.

No input names a company, person or product, so all inputs are quoted verbatim and none is
paraphrased. The six responses were checked the same way. A one-off script outside the repo
rendered the file from `cases.jsonl` and `calls.jsonl`, checked every quoted response against
`diffs_C_vs_D.csv`, and computed every count in the text. The case IDs are listed, so anyone with
the run directory can check the quotes against the chain.

Rejected alternative: a `model-diff examples` command. The selection is a one-time editorial
choice, and a command would add an interface for it.

Because `examples.md` is public, the published README no longer says that no public file holds
case text. It now names `examples.md` as the one exception; a test covers both wordings.

## D33. Public-safety pass before the evidence-pack commit (2026-10-12, author request)

The scan covered every tracked or about-to-be-tracked file. That is wider than the folders the
author named; it adds `DECISIONS.md`, `src/`, `tests/` and the fixtures. It also covered
`git log -p --all` (6 commits).

Name check:
- Candidates were words capitalized mid-sentence in all 780 run inputs, the full case pool and
  every recorded response, plus the people's names and the product name known from the judge's
  sentences (D30).
- A second pass took every capitalized or all-caps token in the inputs, wherever it sits.
- Every hit is an ordinary word, a label, a category name, or a statute or regulation name.
  None of the known names appears in a public file or in history.

Key check:
- The only key-shaped string is the dummy `api_key="test…"` in `tests/test_wire.py`.
- The other hits are LegalBench URLs and SHA-256 digests.

Case-text check:
- Verbatim 40-character spans of case inputs appear only in `examples.md`.
- History holds no input spans. Its 24 response-span matches are prompt phrases that models
  repeat back.

Nothing needed changing. One judgment call is left to the author: example 2's clause mentions "a
particular genetic trait". It names no company, but it hints at the kind of service.

The failed first launch's directory, `runs/20261012T222724Z` (frozen inputs only, no
`calls.jsonl`, no API calls), was deleted at the author's request. This supersedes "left in place"
in D23.

## D34. Three wording edits before the evidence-pack commit (2026-10-12, author decisions)

1. **Direction rule on relevance tasks.** On `privacy_policy_qa`, the author reads the direction
   rule as "more likely to mark Relevant = more_lenient". On relevance tasks, "more flags" and
   "requires more before accepting" point opposite ways. The sentence is stored in
   `score/reliability.py` (`DIRECTION_READINGS`), and the report adds it to the judge-reliability
   method only for tasks the run includes. All four `privacy_policy_qa` label changes in the
   review sample already follow this reading, in both the judge's labels and the reference
   labels (rows 3, 4, 11, 12).
   `data/tasks.yaml` still sets no `stricter_when` for this task, so `per_task.md` reports its
   direction as "more flags" without a stricter or lenient reading. Setting it is a separate
   decision.
2. **`examples.md` gains a line on the 13/2 split.** The author's draft said example 2 was one
   of the two answers that moved away from Relevant. The recorded answers show the opposite:
   example 2 (`-01104`) moved toward Relevant, and example 1 (`-04433`) moved away. The line
   therefore names example 1, and the generator asserts both directions.
3. **Which judge labels to trust.** The author reads `misread_instruction` (0 of 3) as unreliable,
   and `stricter` (7 of 8) and `more_lenient` (7 of 7) as the labels that held. That reading is
   recorded through `reliability --unreliable-label/--held-label`, and the counts are filled from
   the data. `reliability` refuses any reading the counts contradict: an "unreliable" label must
   have matched under half its uses, and a "held" label over half. The sentence also names any
   other label that matched every use (`format_change`, 4 of 4), so "the labels that held" does
   not read as a complete list.

## D35. Sonnet 4.5 retirement differs by platform (2026-10-14, author decision)

The retirement date recorded in D10, D16 and `config.yaml`, 2026-11-30, covers only Anthropic-operated
platforms: the Claude API, Claude Platform on AWS and Microsoft Foundry. It is still marked
"tentative". Source: https://platform.claude.com/docs/en/about-claude/model-deprecations, checked
2026-10-14. Partner clouds set their own schedules:
- Amazon Bedrock lists `anthropic.claude-sonnet-4-5-20250929-v1:0` as Legacy from 2026-10-08,
  with public extended access from 2027-01-08 and end of life on 2027-04-08. Source:
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html, checked
  2026-10-14.
- Google Vertex AI lists it as generally available, with retirement "not sooner than"
  2026-09-29 and no date announced. Source:
  https://docs.cloud.google.com/vertex-ai/generative-ai/docs/partner-models/claude/sonnet-4-5,
  last updated 2026-10-13.

`docs/writeup.md` now states all three instead of a single November 30 retirement.
