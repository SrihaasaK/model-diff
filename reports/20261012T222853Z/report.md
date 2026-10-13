# Model-change evidence: Sonnet 4.5 → Sonnet 5.5

Run `20261012T222853Z`, started 2026-10-12 22:28 UTC. 780 public LegalBench cases in 5 compliance tasks, each sent 3 times to each of 4 arms. Every call is recorded in a SHA-256 hash chain; `model-diff verify 20261012T222853Z` re-checks it offline. Chain head at report time: `142a627cd7aa27b7e0f87087409832a9d23ece4c14d7537b6a82bef962f1c151`.

Models, as reported by the models endpoint when the run started (2026-10-12): `claude-sonnet-4-5-20250929` (Claude Sonnet 4.5, lifecycle `active`), `claude-sonnet-5-5` (Claude Sonnet 5.5, lifecycle `active`); judge `claude-haiku-5-5` (Claude Haiku 5.5, lifecycle `active`).

## Primary comparison: the model switch alone (arm C vs arm D)

Arm C is Sonnet 4.5, temperature 1.0; arm D is Sonnet 5.5, thinking off. They receive identical prompts and are the step on the attribution path whose intended difference is the model alone. Their request parameters are not byte-identical: model: claude-sonnet-4-5-20250929 → claude-sonnet-5-5; temperature: 1.0 → not sent (API default); thinking: not sent (API default) → between_tools. Each difference expresses the same intended setting in the form each model accepts (DECISIONS.md D26).

| Measure | Sonnet 4.5 (arm C) | Sonnet 5.5 (arm D) | Change |
|---|---|---|---|
| Accuracy, all tasks (95% Wilson CI) | 74.2% (71.0%–77.2%) | 77.7% (74.6%–80.5%) | +3.5 pts (exact McNemar p = 0.016; 45 cases only arm C got right, 72 only arm D) |
| Final answers that changed | | | 127 of 780 (16.3%): 122 label changes, 5 where one side gave no parseable label |
| Same label, strict JSON compliance changed | | | 378 of 780 |
| Noise floor: chance two runs of the same arm disagree | 2.9% | 3.1% | |
| Single runs of the two arms disagree | | | 16.7% of run pairs |
| Parse failures (per call) | 0.04% | 1.03% | +1.0 pts |
| Not exactly the requested JSON (per call) | 68.50% | 18.55% | -50.0 pts |
| Refusals (per call) | 0.00% | 0.00% | +0.0 pts |
| Mean output tokens per call (thinking included) | 69 | 114 | Sonnet 5.5 thinking: 0 |

Per task, with flag rates and the direction of change, from `per_task.md`:

| Task | Accuracy Sonnet 4.5 | Accuracy Sonnet 5.5 | Change | Flag rate change | Answers changed | Direction |
|---|---|---|---|---|---|---|
| `insurance_policy_interpretation` | 61.7% | 61.7% | +0.0 pts | -2.3 pts | 50 | mixed |
| `privacy_policy_qa` | 58.5% | 64.0% | +5.5 pts | +5.5 pts | 15 | more flags |
| `sara_entailment` | 79.5% | 89.5% | +10.0 pts | +10.5 pts | 38 | more flags |
| `telemarketing_sales_rule` | 93.6% | 89.4% | -4.3 pts | -4.3 pts | 8 | mixed |
| `unfair_tos` | 88.5% | 87.5% | -1.0 pts | -12.0 pts (reweighted) | 16 | more lenient |

![Accuracy by task, Sonnet 4.5 vs Sonnet 5.5, with the base model's run-to-run range as a band](accuracy_by_task.png)

### What changed between arm C and arm D

| Category | `insurance_policy_interpretation` | `privacy_policy_qa` | `sara_entailment` | `telemarketing_sales_rule` | `unfair_tos` | All |
|---|---|---|---|---|---|---|
| `same` | 47 | 115 | 106 | 0 | 7 | 275 |
| `A_right_B_wrong` | 22 | 2 | 4 | 5 | 7 | 40 |
| `A_wrong_B_right` | 22 | 13 | 29 | 3 | 5 | 72 |
| `both_wrong_differently` | 6 | 0 | 0 | 0 | 4 | 10 |
| `format_drift` | 36 | 70 | 61 | 39 | 177 | 383 |
| `refusal_change` | 0 | 0 | 0 | 0 | 0 | 0 |

Of the 383 `format_drift` cases, 378 kept the same label and changed only strict JSON compliance (356 where Sonnet 4.5's repeats mostly broke the format, 22 the reverse), and 5 are cases where one side gave no parseable label. How each arm's responses missed the requested format (per call): arm C: JSON in a Markdown code fence 1561, text before or after the JSON 41, no parseable label 1; arm D: text before or after the JSON 410, no parseable label 24. A lenient parser reads these labels; a strict one would reject them. The judge described 30 of this pair's changes, the cases in the human-review sample; the full set of changes was not judged.

![Diff categories by task](diff_categories_by_task.png)

## What a vendor sees if it does not pin settings (arm A vs arm B)

Arm A is Sonnet 4.5, temperature 0; arm B is Sonnet 5.5, API defaults: the configuration a team gets by switching the model ID and dropping the parameters the new model rejects. This mixes three changes: temperature, model, and thinking (with its larger output limit).

| Measure | Sonnet 4.5 (arm A) | Sonnet 5.5 (arm B) | Change |
|---|---|---|---|
| Accuracy, all tasks (95% Wilson CI) | 74.7% (71.6%–77.7%) | 80.4% (77.5%–83.0%) | +5.6 pts (exact McNemar p = 1.9e-05; 30 cases only arm A got right, 74 only arm B) |
| Final answers that changed | | | 112 of 780 (14.4%): 112 label changes, 0 where one side gave no parseable label |
| Same label, strict JSON compliance changed | | | 420 of 780 |
| Noise floor: chance two runs of the same arm disagree | 0.9% | 2.5% | |
| Single runs of the two arms disagree | | | 14.5% of run pairs |
| Parse failures (per call) | 0.04% | 0.00% | -0.0 pts |
| Not exactly the requested JSON (per call) | 69.10% | 12.69% | -56.4 pts |
| Refusals (per call) | 0.00% | 0.00% | +0.0 pts |
| Mean output tokens per call (thinking included) | 67 | 182 | Sonnet 5.5 thinking: 74 |

| Category | `insurance_policy_interpretation` | `privacy_policy_qa` | `sara_entailment` | `telemarketing_sales_rule` | `unfair_tos` | All |
|---|---|---|---|---|---|---|
| `same` | 47 | 120 | 76 | 1 | 4 | 248 |
| `A_right_B_wrong` | 19 | 2 | 3 | 2 | 4 | 30 |
| `A_wrong_B_right` | 22 | 12 | 35 | 3 | 2 | 74 |
| `both_wrong_differently` | 5 | 0 | 0 | 0 | 3 | 8 |
| `format_drift` | 40 | 66 | 86 | 41 | 187 | 420 |
| `refusal_change` | 0 | 0 | 0 | 0 | 0 | 0 |

The judge (claude-haiku-5-5) described each changed case in this comparison: format change 260, other 167, more lenient 63, stricter 29, misread instruction 8, judge unparseable 5. These are model judgements, not ground truth.

## Sequential attribution along A → C → D → B

Of the 112 answers that differ between arm A and arm B: the model step alone moved 81, the thinking step alone moved 27, the temperature step alone moved 1; 3 moved at more than one step. This is sequential attribution along one path; factors can interact, so a different order of changes could split the shares differently. Full table, with each step's exact parameter changes, in `attribution.md`.

## Judge reliability

The judge's label for the nature of each change was compared with a reference label on the 30-case review sample (arm C vs arm D, equal shares per change category). Reference labels are a rule-based first pass by the harness author's agent, not blind to the judge's labels, confirmed against a reviewer rule table, with disputed rows resolved individually by the author.

The judge matched the reference on **23 of 30 cases (76.7%)**; on the 29 cases where the judge's answer could be parsed, 79.3%. The reference differs from the judge on 7 cases; the author's review changed 5 of the agent's first-pass labels. The judge's `misread_instruction` label matched 0 of 3 reference labels and should be treated as unreliable. `stricter` (7 of 8) and `more_lenient` (7 of 7) are the labels that held; `format_change` also matched all 4 of its uses.

| Judge label | Cases | Matched the reference |
|---|---|---|
| format_change | 4 | 4 |
| judge_unparseable | 1 | 0 |
| misread_instruction | 3 | 0 |
| more_lenient | 7 | 7 |
| other | 7 | 5 |
| stricter | 8 | 7 |

Disagreements (row numbers are positions in the review sample):

| Row | Case | Change category | Judge | Reference | Reviewer note |
|---|---|---|---|---|---|
| 6 | `sara_entailment-00240` | A_right_B_wrong | misread_instruction | other | the question was the same; 5.5 read "applies" as "governs" rather than "is triggered" |
| 8 | `unfair_tos-02583` | A_right_B_wrong | misread_instruction | other | category choice on a multi-category task |
| 10 | `insurance_policy_interpretation-00074` | A_wrong_B_right | stricter | more_lenient | confirmed by reviewer rule table |
| 14 | `sara_entailment-00143` | A_wrong_B_right | misread_instruction | other | 4.5 misapplied the clause, 5.5 read it correctly; a reasoning-quality difference, not a direction |
| 17 | `insurance_policy_interpretation-00017` | both_wrong_differently | judge_unparseable | more_lenient | confirmed by reviewer rule table |
| 25 | `insurance_policy_interpretation-00102` | format_drift | other | format_change | confirmed by reviewer rule table; minor reasoning difference not detected by the differ |
| 28 | `sara_entailment-00079` | format_drift | other | format_change | caveat changes neither conclusion nor basis |

The direction rule used for the reference labels, verbatim (its row numbers are review-sample positions):

- "stricter" = Sonnet 5.5 is more likely than 4.5 to flag, deny, find a violation, or require more before accepting. "more_lenient" = the reverse.
- A move TO Ambiguous FROM Yes/Covered/Entailment is stricter; TO Ambiguous FROM No/Not covered/Contradiction is more_lenient. Apply this consistently; it resolves the judge's conflict on rows 2 and 10.
- "misread_instruction" only when 5.5 answered a different question than the one asked (check the input, not the judge's sentence).
- "format_change" for same-label rows where only the code fence, whitespace or JSON shape differs.
- "other" for category choices on multi-category tasks (unfair_tos categories) and for same-label rows with minor reasoning differences; put the reason in rule_note.

## All arms

| Arm | Configuration | Accuracy (95% CI) | Noise floor | Unanimous cases | Parse fail | Refusal | Mean output tokens | Mean thinking tokens |
|---|---|---|---|---|---|---|---|---|
| A | Sonnet 4.5, temperature 0 | 74.7% (71.6%–77.7%) | 0.9% | 98.7% | 0.04% | 0.00% | 67 | n/a |
| B | Sonnet 5.5, API defaults | 80.4% (77.5%–83.0%) | 2.5% | 96.3% | 0.00% | 0.00% | 182 | 74 |
| C | Sonnet 4.5, temperature 1.0 | 74.2% (71.0%–77.2%) | 2.9% | 95.6% | 0.04% | 0.00% | 69 | n/a |
| D | Sonnet 5.5, thinking off | 77.7% (74.6%–80.5%) | 3.1% | 95.5% | 1.03% | 0.00% | 114 | 0 |

## `unfair_tos` per-category precision and recall, arm C vs arm D (exploratory)

Per-category numbers rest on about two dozen cases per label and are exploratory; the per-task tables use the pooled "any unfair" flag.

| Label | Support | Precision Sonnet 4.5 | Recall Sonnet 4.5 | Precision Sonnet 5.5 | Recall Sonnet 5.5 |
|---|---|---|---|---|---|
| Arbitration | 15 | 75.0% | 100.0% | 78.9% | 100.0% |
| Choice of law | 24 | 100.0% | 91.7% | 100.0% | 91.7% |
| Content removal | 23 | 100.0% | 78.3% | 94.7% | 78.3% |
| Contract by using | 23 | 100.0% | 82.6% | 100.0% | 65.2% |
| Jurisdiction | 23 | 95.7% | 95.7% | 95.8% | 100.0% |
| Limitation of liability | 23 | 88.5% | 100.0% | 95.7% | 95.7% |
| Other | 23 | 88.9% | 69.6% | 76.0% | 82.6% |
| Unilateral change | 23 | 83.3% | 87.0% | 70.0% | 91.3% |
| Unilateral termination | 23 | 73.3% | 95.7% | 87.0% | 87.0% |

## Method

1. 780 cases from 5 LegalBench test splits (commit `daec8237410a`), drawn with seed 42; `unfair_tos` is label-stratified, the others random or whole.
2. Every case went 3 times to each arm through the Message Batches API with byte-identical prompts; arms differ only in the parameters stored with every record.
3. Responses are parsed as JSON; an arm's final answer is the majority of its repeats; refusals come from the API's stop reason, a rule set, and the judge.
4. The primary comparison is the model step (arm C vs arm D); the configuration a team gets without pinning settings (arm A vs arm B) is reported second, and the change is attributed along the control arms.
5. Each call is hash-chained to the frozen config, cases, prompts, and models snapshot.
6. Judge reliability: Reference labels are a rule-based first pass by the harness author's agent, not blind to the judge's labels, confirmed against a reviewer rule table, with disputed rows resolved individually by the author. On `privacy_policy_qa`, the direction rule is read as "more likely to mark Relevant = more_lenient," since "more flags" and "requires more before accepting" diverge on relevance tasks.

## Caveats

- **Noise floor.** The primary pair runs at temperature 1.0: two runs of arm C disagree on 2.9% of cases and two runs of arm D on 3.1%. Changes at or below these rates are not evidence of a model change. Final answers are majorities of three repeats, which reduces but does not remove that noise.
- **Sampling.** Sample sizes per task: `insurance_policy_interpretation` 133, `privacy_policy_qa` 200, `sara_entailment` 200, `telemarketing_sales_rule` 47, `unfair_tos` 200. The small tasks have wide intervals. `unfair_tos` is label-stratified, so its unweighted accuracy and flag rate describe the sample; reweighted figures are given. Pooled accuracy is over the sample as drawn.
- **Settings.** The primary pair's request parameters differ as listed above; DECISIONS.md D26 explains why each difference is the same intended setting in the form each model accepts.
- **Attribution** is sequential along one path, and interactions between factors mean another order could split the shares differently.
- **Judge.** Refusal decisions for ambiguous responses and the change descriptions come from claude-haiku-5-5, which cannot run deterministically; its answers are recorded once and reused.
- **Reference labels** are LegalBench's. Some are contestable (the insurance task's labels come from crowd agreement, including an explicit "ambiguous" class), so accuracy measures agreement with them.
- **One point in time.** Model behavior behind a pinned ID can still change; the models-list snapshot records what the API reported when the run started.
- **Output limit.** Calls that stopped at their arm's `max_tokens` limit: arm A 1 (`sara_entailment` 1; 1 without a parseable label); arm C 1 (`sara_entailment` 1; 1 without a parseable label); arm D 22 (`sara_entailment` 22; 22 without a parseable label). Truncated answers are reasoning written into the visible response before the JSON. Those without a label count as parse failures and as wrong answers, which understates that arm on that task.
- **Differ.** Three same-label review rows the differ classed as `format_drift` (`insurance_policy_interpretation-00102`, `sara_entailment-00079`, `telemarketing_sales_rule-00013`) carry minor reasoning differences the differ did not detect; in the last, the reviewer judged that the legal basis changed. `format_drift` therefore slightly understates substantive change.
- **Reweighting.** The reweighted `unfair_tos` figures give 90.6% of the weight to the 23 sampled `Other` cases, so they are much less certain than the unweighted ones.

## Cost

| Item | Spend |
|---|---|
| arm A latency probe | \$0.10 |
| arm A preflight | \$0.00 |
| arm A subject | \$2.22 |
| arm B latency probe | \$0.16 |
| arm B preflight | \$0.00 |
| arm B subject | \$3.07 |
| arm C latency probe | \$0.10 |
| arm C preflight | \$0.00 |
| arm C subject | \$2.24 |
| arm D latency probe | \$0.10 |
| arm D preflight | \$0.00 |
| arm D subject | \$2.28 |
| judge | \$0.07 |
| **Total** | **\$10.33** |

Cost cap \$35.00. After the pilot, the run projected \$11.80 from measured usage and kept arms A, B, C, D. Prices: Anthropic list prices on 2026-10-12, with the Batch API at half price.

## Reproduce and verify

```sh
uv run model-diff verify 20261012T222853Z   # offline: re-walks the hash chain and frozen artifacts
uv run model-diff report 20261012T222853Z   # offline: rebuilds this report from the run directory
```

## Data and licenses

Cases are from LegalBench (Guha et al., 2023). Task licenses: `insurance_policy_interpretation` CC BY 4.0; `privacy_policy_qa` MIT; `sara_entailment` MIT; `telemarketing_sales_rule` CC BY 4.0; `unfair_tos` CC BY 4.0. Source datasets should be cited as their LegalBench task cards ask.
