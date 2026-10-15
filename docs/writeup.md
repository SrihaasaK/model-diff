# Sonnet 4.5 → 5.5: What Changed on 780 Compliance Cases

Srihaasa Karyampudi · October 2026 · numbers from commit 4f8a3c2, run 20261012T222853Z

## The finding

Replaying 780 public compliance cases through Sonnet 4.5 and Sonnet 5.5 with identical prompts, 16.3% of final answers changed against a 3% noise floor. The model switch alone drove 81 of the 112 answers that change in an unpinned upgrade, and the direction varied by rule area: two tasks flagged more often, one got more lenient, and two were mixed, with telemarketing down a net 2 cases of 47, too few to call.

Anthropic retires Sonnet 4.5 from its own API on November 30, 2026; Amazon Bedrock lists it as legacy from October 8, 2026 with end of life on April 8, 2027, and Google Vertex AI has announced no date. Any tool still running on it will move to a newer model within months, and this is a measured look at the kind of change that move makes to compliance-style answers: not whether the new model is better on average (it is, by 3.5 points), but which answers change, in which direction, and whether the change can be told apart from run-to-run noise.

## Headline numbers

With identical prompts and the model as the intended difference, Sonnet 5.5 (thinking off) scored 77.7% against Sonnet 4.5's 74.2% on 780 LegalBench cases. That is +3.5 points, exact McNemar p = 0.016: 72 cases only Sonnet 5.5 got right, 45 only Sonnet 4.5.

| Model-only comparison | Sonnet 4.5 | Sonnet 5.5 (thinking off) |
| --- | --- | --- |
| Accuracy (95% CI) | 74.2% (71.0–77.2) | 77.7% (74.6–80.5) |
| Cases only this model got right | 45 | 72 |
| Final answers changed between models (majority of 3 runs) | 127 of 780 (16.3%) |  |
| Single runs that disagree across models | 16.7% |  |
| Noise floor: single runs that disagree within one model | 2.9–3.1% |  |
| Same label, only JSON formatting changed | 378 of 780 |  |

The 16.3% is the number that matters for a vendor. It counts majority-of-three final answers; the like-for-like figure, single runs compared across models, is 16.7% against 2.9–3.1% within one model. Either way, about one answer in six is a different answer, more than five times what the same model produces on its own.

**What an unpinned upgrade looks like.** A vendor that moves from 4.5 at temperature 0 to 5.5 at its defaults (temperature 1, thinking on) with max_tokens raised from 512 to 16,000 changes several things at once. Of the 112 answers that differ between those two configurations, the model step alone moved 81 (72.3%), the thinking step alone 27 (24.1%), and temperature alone 1 (0.9%); 3 moved at more than one step. This is sequential attribution along one path (temperature first, then model, then thinking), the thinking step also carries the larger output limit, and the factors can interact, so the split is indicative rather than exact.

## Where it moved

The average hides the part a compliance team cares about: the direction of change differs by rule area, and the largest drop rests on too few cases to say whether accuracy really fell.

| Task (LegalBench) | What the model decides | Direction of change | Accuracy change |
| --- | --- | --- | --- |
| sara_entailment | Does a tax statute entail the conclusion | More flags (flag rate +10.5 pts) | +10.0 pts |
| privacy_policy_qa | Is a policy clause relevant to the question | More flags (13 of 15 changed answers moved toward Relevant) | +5.5 pts |
| unfair_tos | Is a terms-of-service clause unfair | More lenient (reweighted flag rate −12.0 pts) | −1.0 as drawn; 4.5 at 71.8% vs 5.5 at 83.2% reweighted |
| insurance_policy_interpretation | Does the policy cover the claim | Mixed (10 toward the flag, 13 away, 27 between non-flag labels) | Flat, with 50 answers changed |
| telemarketing_sales_rule | Does the conduct violate the rule | Mixed | 93.6% → 89.4% (−4.3 pts: 5 lost, 3 gained) |

Three notes on reading this table:

- **Telemarketing had the largest drop,** but the drop is 5 cases lost against 3 gained, a net 2 of 47. No per-task significance test was run, and that is too few cases to say whether accuracy really fell. The only other dip, unfair_tos at −1.0 as drawn, reverses when reweighted.
- **The unfair-terms reversal is fragile.** On the sample as drawn, accuracy dipped 1.0 point. Reweighted to the natural mix of ordinary and unfair clauses, 5.5 flags 12 points fewer clauses and accuracy goes from 4.5's 71.8% to 5.5's 83.2%. That rests on 23 sampled ordinary clauses, which carry 90.6% of the reweighted total.
- **Insurance looks unchanged and isn't.** Both models land at the same accuracy, yet 50 answers on that task changed, split both ways. A customer who only checks the aggregate would see nothing.

For privacy_policy_qa, "more flags" means more clauses marked Relevant. The per-task table reports that direction and no verdict. Where the review sample needed a label, a move toward Relevant was read as more lenient, and the report's method says so.

## Three examples

All three are privacy-policy cases, quoted verbatim from the recorded calls; none of the inputs names a company, person or product. The exact clause, question and both answers are in `reports/20261012T222853Z/examples.md`; the three quote blocks are quoted below from that file.

**Example 1 — privacy_policy_qa-04433. 4.5 right, 5.5 wrong, and against the task's own direction.** Sonnet 4.5 marked the clause Relevant; Sonnet 5.5 marked it Irrelevant. 13 of the 15 changed answers on this task moved toward Relevant; this is one of the two that moved the other way. It is the reason a per-task direction is not a per-case guarantee.

> **Clause:** Once we have received your data, we will use strict procedures and security features to try to prevent unauthorized access.
>
> **Question:** are you certified to be secure?
>
> **Sonnet 4.5:**
>
> ````text
> ```json
> {"label": "Relevant", "rationale": "The clause addresses security measures and procedures to prevent unauthorized access, which directly relates to the question about security certification and being secure."}
> ```
> ````
>
> **Sonnet 5.5:**
>
> ````text
> {"label": "Irrelevant", "rationale": "The clause describes security procedures used to prevent unauthorized access but says nothing about holding any security certification or third-party attestation, which is what the question asks."}
> ````

**Example 2 — privacy_policy_qa-01104. 4.5 wrong, 5.5 right, with the task's direction.** Sonnet 4.5 marked the clause Irrelevant; Sonnet 5.5 marked it Relevant. This is the typical shape of the change on this task: the newer model flags more.

> **Clause:** For example, Aggregate Information may include a statement that "30% of our female users share a particular genetic trait," without providing any data or testing results specific to any individual user.
>
> **Question:** do you publish my data
>
> **Sonnet 4.5:**
>
> ````text
> {"label": "Irrelevant", "rationale": "This clause only provides an example of how aggregate information might be presented and does not address whether the company publishes individual user data."}
> ````
>
> **Sonnet 5.5:**
>
> ````text
> {"label": "Relevant", "rationale": "The clause describes how aggregated, de-identified statistics may be shared without exposing any individual user's data, which partly answers whether the user's own data is published."}
> ````

**Example 3 — format drift only.** Both models gave the same label; only strict JSON compliance differed. This is the shape of 378 of the 780 comparisons and is why a parse-rate change should be separated from a label change before anyone calls it a regression.

> `privacy_policy_qa-09917`
>
> **Sonnet 4.5:**
>
> ````text
> ```json
> {"label": "Irrelevant", "rationale": "This clause discusses opting in or out of advertising through partners but does not specify what data is collected."}
> ```
> ````
>
> **Sonnet 5.5:**
>
> ````text
> {"label": "Irrelevant", "rationale": "The clause only says users may need to opt in or out of advertising through partners and does not describe what data is collected."}
> ````

One more from the review sample, paraphrased from the recorded reasoning rather than quoted. On insurance_policy_interpretation-00018, 4.5 answered Yes (creek water built up rapidly and entered the basement, meeting every element of the flooding definition); 5.5 with thinking off answered Ambiguous in 2 of 3 runs (the facts plausibly fit, but "large volume" is undefined, so a small creek's overflow may not meet the threshold). The gold label is Yes. Two things make it worth showing. It is a stricter change on a task that was mixed overall, so a per-task direction says little about any one case. And with thinking on, 5.5 answered Ambiguous in only 1 of 3 runs, so the majority flips to Yes: this case sits on the line, and which side wins depends on settings a vendor cannot see without replaying both.

## Format drift is half the comparisons, and it is not a regression

383 of the 780 model-only comparisons are format drift, 76% of the 505 cases that changed at all. In 378 of them both models gave the same label and only strict JSON compliance changed: in 356 it was mostly Sonnet 4.5 breaking the requested format, in 22 the reverse. In the remaining 5, Sonnet 5.5 returned no parseable label at all, truncated at the output-token limit on tax-statute cases, and those count against 5.5 in the accuracy numbers above.

Counting label changes and format changes together gives 505 of 780 (65%), and a literal string diff of the raw outputs would flag every case, because the rationales are reworded on almost every run: 0 of 780 raw outputs matched across models, and even within one arm (Sonnet 4.5 at temperature 1.0) only 13 of 780 cases gave three identical responses (both figures come from the per-call records, not the published folder). Separating label changes from format changes is what gets the real change down to 16.3%, and it is the first thing a reviewer should ask of any "the model changed" claim. The count cuts the other way too: three of the 30 reviewed rows were same-label cases whose reasoning differed in ways the differ cannot detect, so the format-drift figure slightly understates real change.

## How reliable the automated change labels are

A Haiku 5.5 judge was asked to name the change type for every unpinned-upgrade (A vs B) difference and for a 30-case sample of the model-only differences, drawn evenly across change categories; the full model-only set was not judged. Labels were one of five: stricter, more_lenient, misread_instruction, format_change, other. On the 30-case sample the judge matched the reference labels on 23 of 30 (76.7%), and on 23 of 29 where its answer could be parsed (79.3%).

| Change type | Judge matched | 95% interval (Wilson) | Note |
| --- | --- | --- | --- |
| stricter | 7 of 8 | 53–98% | Held |
| more_lenient | 7 of 7 | 65–100% | Held |
| format_change | 4 of 4 | 51–100% |  |
| other | 5 of 7 | 36–92% |  |
| misread_instruction | 0 of 3 | 0–56% | Treat as "other" |
| judge gave no parseable answer | 0 of 1 | 0–79% | Counted as a miss |

The reference labels are a rule-based first pass by the harness author's agent, not blind to the judge's labels, confirmed against a reviewer rule table with disputed rows resolved individually; that review changed 5 of the 30 first-pass labels. The direction rule: "stricter" means 5.5 is more likely to flag, deny, or require more; a move to Ambiguous from Yes, Covered or Entailment is stricter, from No or Contradiction more lenient. On privacy_policy_qa the rule does not apply cleanly, and those four review rows were labeled by the "more Relevant = more lenient" reading.

## Method

1. **Cases.** 780 labeled cases from five public LegalBench tasks (insurance_policy_interpretation, privacy_policy_qa, sara_entailment, telemarketing_sales_rule, unfair_tos), fixed before any model was called.
2. **Arms.** Four configurations, same prompts and parser throughout: A = Sonnet 4.5 at temperature 0; C = Sonnet 4.5 at temperature 1.0, no thinking; D = Sonnet 5.5 with thinking off and temperature left at its default; B = Sonnet 5.5 at its defaults (thinking on) with max_tokens raised from 512 to 16,000. C vs D is the model-only comparison; A vs B is the unpinned upgrade; the path A → C → D → B isolates temperature, then model, then thinking.
3. **Noise floor.** Each arm was run three times on the same cases; the share of answers that change between two single runs of the same arm is the floor any cross-model change has to clear: 2.9–3.1% for the model-only arms, 0.9% for 4.5 at temperature 0, 2.5% for 5.5 at its defaults.
4. **Scoring and diff.** Every call recorded with prompt hash, request id, raw response, parsed label, tokens and latency. Labels scored against gold, disagreements diffed into six categories, and a Haiku 5.5 judge asked to name the change type; a 30-case sample was checked against a reviewer rule table, with disputed rows resolved individually, to measure the judge.
5. **Statistics.** Accuracy with 95% confidence intervals; paired difference tested with exact McNemar on the discordant cases. No per-task significance test was run.

**"Identical settings" is not literally true.** Sonnet 5.5 rejects any non-default temperature, so arm D omits the temperature parameter and sends an explicit thinking-off flag, while arm C sets temperature 1.0 explicitly. The report states this and the repository's DECISIONS.md (D26) records why.

Total API cost for the run, judge calls included: about $10.33.

## Verify it yourself

Every API call in the run is a record in a hash-chained manifest (10,152 records). The chain head for run `20261012T222853Z` is:

```
142a627cd7aa27b7e0f87087409832a9d23ece4c14d7537b6a82bef962f1c151
```

Anyone given the run directory, placed under runs/ in a clone of the repository, can recompute it:

```
uv run model-diff verify 20261012T222853Z
```

That recomputes the chain and fails if any record has been altered, dropped or reordered since the run. The per-call records and manifest live in the run directory, which is not in the public repository because it holds the raw case text and every raw response; it is available on request, with the dataset attributions it requires, to anyone who wants to check the head, and this dated post is the anchor the head is checked against. The published folder `reports/20261012T222853Z/` holds the report, per-task table, attribution, examples, both charts and the JSON the numbers above come from (`scores.json`, `diff_summary.json`, `run_config.json`, `models_snapshot.json`, `HEAD.json`). The public files contain no case text other than the three quoted examples and the paraphrased insurance case above.

Repository: [github.com/SrihaasaK/model-diff](https://github.com/SrihaasaK/model-diff)

## What this means if your tool is on 4.5

If your product makes compliance-style calls on Sonnet 4.5, this is the kind of change to expect when it moves: about one answer in six different, better on average, with the direction depending on which rule the answer is about, and at least one area where the cases are too few to say which way it went. These are five public tasks with one prompt each, not your prompts or your cases. None of this shows up in an aggregate accuracy number, and none of it is in your logs unless you replayed a fixed suite before and after.

I built the harness that produced these numbers and I am running it against adviser- and broker-dealer-facing tools while the old model can still be called. If you ship one and want the same comparison on your own prompts and a sample of your own cases, with an evidence pack you can hand a compliance reviewer, reply and I will send the details.
