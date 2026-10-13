# Sequential attribution along A → C → D → B

Run `20261012T222853Z`. Each arm differs from the one before it by one factor. Of the 780 cases, 112 have a different final answer in arm A (Sonnet 4.5, temperature 0) and arm B (Sonnet 5.5, API defaults). For each of those, the steps whose two arms give different final answers are the factors that moved it.

| Arm | Configuration | Step | Request parameters changed from the previous arm | Accuracy (95% CI) | Answers changed vs previous arm | Changed answers moved by this step alone | Moved by this step with others |
|---|---|---|---|---|---|---|---|
| A | Sonnet 4.5, temperature 0 | start | | 74.7% (71.6%–77.7%) | | | |
| C | Sonnet 4.5, temperature 1.0 | temperature | temperature: 0.0 → 1.0 | 74.2% (71.0%–77.2%) | 10 of 780 (1.3%) | 1 (0.9%) | 1 |
| D | Sonnet 5.5, thinking off | model | model: claude-sonnet-4-5-20250929 → claude-sonnet-5-5; temperature: 1.0 → not sent (API default); thinking: not sent (API default) → between_tools | 77.7% (74.6%–80.5%) | 127 of 780 (16.3%) | 81 (72.3%) | 3 |
| B | Sonnet 5.5, API defaults | thinking | max_tokens: 512 → 16000; thinking: between_tools → not sent (API default) | 80.4% (77.5%–83.0%) | 69 of 780 (8.8%) | 27 (24.1%) | 3 |

**Of the 112 answers that differ between arm A and arm B, the model step alone moved 81 (72.3%), the thinking step alone moved 27 (24.1%), the temperature step alone moved 1 (0.9%); 3 moved at more than one step.**

Combinations of steps that moved each changed answer: model: 81, model+thinking: 2, temperature: 1, temperature+model+thinking: 1, thinking: 27.

Notes:

- This is sequential attribution along one path. Factors can interact, so changing them in a different order could split the shares differently. This order is the only one the API allows, because Sonnet 5.5 cannot run at temperature 0.
- A step can move an answer and a later step move it back; such cases are not among the changed answers.
- The parameter column lists every request difference between consecutive arms, not only the named factor. Read it before crediting a step to its factor alone (DECISIONS.md D26 explains each difference in this run).
- Run-to-run noise floors (chance two runs of the same arm disagree): A 0.9%, C 2.9%, D 3.1%, B 2.5%.
