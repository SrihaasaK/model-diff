# Three examples from the model-only comparison

Run `20261012T222853Z`, arm C (Sonnet 4.5, temperature 1.0) vs arm D (Sonnet 5.5, thinking off): the model switch alone. All three cases come from LegalBench `privacy_policy_qa` (MIT, [source](https://github.com/HazyResearch/legalbench/tree/b46bf4ffae90524b2b72aaa30e7745fe9db64481/tasks/privacy_policy_qa)). Inputs and responses are quoted verbatim from the recorded run: none of these inputs names a company, person, or product, so none is paraphrased. Each response shown is the earliest of three repeats that voted for the final answer; the repeat votes are listed beside it. All three cases are in the 30-case review sample, so each has a judge label and a reference label (see Judge reliability in `report.md` for how reference labels were made).

## 1. Sonnet 4.5 right, Sonnet 5.5 wrong (`A_right_B_wrong`)

`privacy_policy_qa-04433`. Gold label: **Relevant**.

Input (verbatim):

````text
Question:
are you certified to be secure?

Clause:
Once we have received your data, we will use strict procedures and security features to try to prevent unauthorized access.
````

Sonnet 4.5 (arm C), final answer **Relevant**; repeats Relevant / Relevant / Relevant; strict format met in 1 of 3 repeats:

````text
```json
{"label": "Relevant", "rationale": "The clause addresses security measures and procedures to prevent unauthorized access, which directly relates to the question about security certification and being secure."}
```
````

Sonnet 5.5 (arm D), final answer **Irrelevant**; repeats Irrelevant / Irrelevant / Irrelevant; strict format met in 3 of 3 repeats:

````text
{"label": "Irrelevant", "rationale": "The clause describes security procedures used to prevent unauthorized access but says nothing about holding any security certification or third-party attestation, which is what the question asks."}
````

Judge (`claude-haiku-5-5`): `stricter`. "Model B applies a narrower standard, requiring the clause to address formal certification or third-party attestation rather than just security practices, so it labels the clause Irrelevant where Model A labeled it Relevant." Reference label (review-sample row 4): `stricter`.

Sonnet 5.5 asks the clause to show a certification, which the question names, and finds it does not. This is one of only 2 of the 15 label changes on `privacy_policy_qa` that moved away from the flag (Relevant); the other 13 moved toward it. By the gold label Sonnet 5.5 is wrong here, and the change runs against the task's usual direction. Sonnet 4.5's answer is also wrapped in a code fence; a label change takes precedence over format in the differ, so the case counts as a label change.

## 2. The opposite direction on the same task (`A_wrong_B_right`)

`privacy_policy_qa-01104`. Gold label: **Relevant**.

Input (verbatim):

````text
Question:
do you publish my data

Clause:
For example, Aggregate Information may include a statement that "30% of our female users share a particular genetic trait," without providing any data or testing results specific to any individual user.
````

Sonnet 4.5 (arm C), final answer **Irrelevant**; repeats Irrelevant / Irrelevant / Irrelevant; strict format met in 2 of 3 repeats:

````text
{"label": "Irrelevant", "rationale": "This clause only provides an example of how aggregate information might be presented and does not address whether the company publishes individual user data."}
````

Sonnet 5.5 (arm D), final answer **Relevant**; repeats Relevant / Relevant / Relevant; strict format met in 3 of 3 repeats:

````text
{"label": "Relevant", "rationale": "The clause describes how aggregated, de-identified statistics may be shared without exposing any individual user's data, which partly answers whether the user's own data is published."}
````

Judge (`claude-haiku-5-5`): `more_lenient`. "Model B labels the clause Relevant by reading its mention of aggregate, non-individual sharing as partially answering whether the user's data is published, while Model A applies a stricter standard and finds it does not address individual data publication at all, so B's standard is looser." Reference label (review-sample row 11): `more_lenient`.

Here Sonnet 5.5 reads the clause more broadly than Sonnet 4.5 and counts a partial answer as Relevant. Read against example 1, the model switch moves answers both ways within one task, so single examples cannot show which way it leans.

13 of the 15 changed answers on this task moved toward Relevant; example 1 is one of the two that moved the other way.

`per_task.md` calls a direction per task only when at least 5 answers cross the flag line and two thirds of them go one way, so this task reads "more flags". In this case the extra Relevant label comes from a looser test for relevance, which is what the judge's and the reference's `more_lenient` describe; the report's method reads the direction rule the same way on this task (more likely to mark Relevant = more_lenient). `data/tasks.yaml` maps flags to stricter or more lenient only for `insurance_policy_interpretation`, `telemarketing_sales_rule` and `unfair_tos`, so `per_task.md` gives this task's direction as "more flags" without that reading.

## 3. Same label, different format (`format_drift`)

`privacy_policy_qa-09917`. Gold label: **Irrelevant**.

Input (verbatim):

````text
Question:
what data does it collect

Clause:
In certain instances, you may need to opt in or opt out of advertising directly through our partners.
````

Sonnet 4.5 (arm C), final answer **Irrelevant**; repeats Irrelevant / Irrelevant / Irrelevant; strict format met in 1 of 3 repeats:

````text
```json
{"label": "Irrelevant", "rationale": "This clause discusses opting in or out of advertising through partners but does not specify what data is collected."}
```
````

Sonnet 5.5 (arm D), final answer **Irrelevant**; repeats Irrelevant / Irrelevant / Irrelevant; strict format met in 3 of 3 repeats:

````text
{"label": "Irrelevant", "rationale": "The clause only says users may need to opt in or out of advertising through partners and does not describe what data is collected."}
````

Judge (`claude-haiku-5-5`): `format_change`. "Both models reach the same Irrelevant label with essentially the same rationale; the only difference is that Model A wraps its JSON in a markdown code fence while Model B outputs bare JSON." Reference label (review-sample row 27): `format_change`.

Both models say Irrelevant for the same reason. Sonnet 4.5 wraps its JSON in a Markdown code fence, though the prompt says "Respond with only a JSON object, with no text before or after it"; Sonnet 5.5 returns bare JSON. The harness's parser still reads the fenced label, so accuracy is unaffected, but a downstream system that parses strictly would reject the 4.5 answer. Of the 780 model-only comparisons, 383 are `format_drift`: in 356 Sonnet 4.5 broke the strict format in most repeats and Sonnet 5.5 did not, in 22 the reverse, and in 5 Sonnet 5.5's final answer was unparseable (all `sara_entailment`; see the output-limit caveat in `report.md`). The judge-reliability review found that a few same-label `format_drift` rows also carry small reasoning differences (see the Differ caveat in `report.md`), so the category slightly understates substantive change.
