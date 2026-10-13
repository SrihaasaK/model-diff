# Per-task results: the model switch alone (Sonnet 4.5 vs Sonnet 5.5)

Run `20261012T222853Z`. Arm C (Sonnet 4.5, temperature 1.0) against arm D (Sonnet 5.5, thinking off): identical prompts, with the model as the intended difference (request parameters that differ: model: claude-sonnet-4-5-20250929 → claude-sonnet-5-5; temperature: 1.0 → not sent (API default); thinking: not sent (API default) → between_tools). Each case ran 3 times per arm; the final answer is the majority.

| Task | License | Cases | Accuracy Sonnet 4.5 | Accuracy Sonnet 5.5 | Change | Flag means | Flag rate Sonnet 4.5 | Flag rate Sonnet 5.5 | Flag change | Answers changed | Direction of change |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `insurance_policy_interpretation` | CC BY 4.0 | 133 | 61.7% | 61.7% | +0.0 pts | Yes | 29.3% | 27.1% | -2.3 pts | 50 | **mixed** (10 toward the flag; 13 away; 27 between non-flag or between flag labels) |
| `privacy_policy_qa` | MIT | 200 | 58.5% | 64.0% | +5.5 pts | Relevant | 12.0% | 17.5% | +5.5 pts | 15 | **more flags** (13 toward the flag; 2 away) |
| `sara_entailment` | MIT | 200 | 79.5% | 89.5% | +10.0 pts | Entailment | 34.5% | 45.0% | +10.5 pts | 38 | **more flags** (28 toward the flag; 5 away; 5 without a label on one side) |
| `telemarketing_sales_rule` | CC BY 4.0 | 47 | 93.6% | 89.4% | -4.3 pts | Yes | 57.4% | 53.2% | -4.3 pts | 8 | **mixed** (3 toward the flag; 5 away) |
| `unfair_tos` | CC BY 4.0 | 200 | 88.5% | 87.5% | -1.0 pts | any unfair category (reweighted) | 36.9% | 24.8% | -12.0 pts | 16 | **more lenient** (0 toward the flag; 7 away; 9 between non-flag or between flag labels) |
| **All tasks** | | 780 | 74.2% | 77.7% | +3.5 pts | | | | | 127 | |

How to read the direction column:

- A changed answer moves *toward the flag* when Sonnet 5.5 gives a flag label and Sonnet 4.5 did not, and *away* in the opposite case. A task is called **more flags** or **fewer flags** when at least 5 changes cross the flag boundary and at least 67% of them cross it the same way. It is called **mixed** otherwise, and **too few changes to call** below that count.
- **Stricter** and **more lenient** are used only where a flag is an adverse finding (`stricter_when` in data/tasks.yaml): for `telemarketing_sales_rule` and `unfair_tos` more flags is stricter, and for `insurance_policy_interpretation` fewer claims judged covered is stricter. A relevance or entailment flag is not adverse, so those tasks report the raw direction.
- In `sara_entailment`, 5 changed answers are cases where one side gave no parseable label (see the output-limit note in report.md); they count as wrong for that side.
- `unfair_tos` was sampled with equal shares per label. Its flag rate is reweighted to the full test split's label mix; its accuracy is over the sample as drawn (reweighted: 71.8% and 83.2%).
