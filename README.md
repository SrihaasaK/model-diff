# model-diff

Reproducible, tamper-evident evidence of what happens to compliance-sensitive classification
outputs when an LLM provider upgrades a model. The first comparison runs Claude Sonnet 4.5
(`claude-sonnet-4-5-20250929`) against Claude Sonnet 5.5 (`claude-sonnet-5-5`) on five public
LegalBench tasks in insurance, tax, privacy, and consumer protection.

## What a run measures

Four arms, defined in `config.yaml`:

| Arm | Model | Parameters | Role |
|---|---|---|---|
| A | Sonnet 4.5 | temperature 0 | headline baseline |
| B | Sonnet 5.5 | API defaults (adaptive thinking; the API rejects temperature 0) | headline candidate |
| C | Sonnet 4.5 | temperature 1.0 | control: isolates temperature |
| D | Sonnet 5.5 | thinking off | control: isolates thinking |

Each case goes to every arm three times with byte-identical prompts. For each arm and task the
scorer reports:

- accuracy against the reference labels, with Wilson 95% intervals;
- the flag (positive-label) rate;
- per-label precision and recall;
- parse-failure, strict-format, and refusal rates;
- latency and tokens;
- the noise floor (how often two runs of the same arm disagree).

The differ compares arm A's majority answers with arm B's, case by case. It sorts each case into
`same`, `A_right_B_wrong`, `A_wrong_B_right`, `both_wrong_differently`, `format_drift`, or
`refusal_change`, and has a judge model describe every change. It then attributes the change to
temperature, model, and thinking by stepping along A → C → D → B.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
cp .env.example .env    # then put your key in .env; it is gitignored and read only by the harness
```

## Commands

```sh
uv run model-diff models                   # startup check: pinned model IDs exist (free)
uv run model-diff propose-tasks            # screen LegalBench, re-check licenses, write data/TASKS.md
uv run model-diff sample                   # after approval: seeded sample to data/cases.jsonl
uv run model-diff dry-run                  # exact input tokens (free), expected cost, cap decision
uv run model-diff run                      # preflight, pilot batch, cost re-projection, main batch, latency probes
uv run model-diff run --run-id <run_id>    # resume an interrupted run without re-sending anything
uv run model-diff score <run_id>           # refusal detection, metrics, noise floor (--offline: no API calls)
uv run model-diff diff <run_id>            # change categories, judge descriptions, attribution, review sample (--offline)
uv run model-diff describe-sample <run_id> # judge descriptions for the model-only review sample (one call per row)
uv run model-diff reliability <run_id>     # judge vs reference labels on the confirmed sample (offline)
uv run model-diff report <run_id>          # report.md, per_task.md, attribution.md, two charts (offline)
uv run model-diff publish <run_id>         # public outputs to reports/<run_id>/ with the chain head (offline)
uv run model-diff verify <run_id>          # re-walk the hash chain (offline)
```

There are two human checkpoints. `sample` and every paid command refuse to run until
`approved: true` is set in `data/tasks.yaml` after reviewing `data/TASKS.md`. `run` refuses a
stale dry run, so the estimate you approve is the one the run uses.

Cost is guarded three ways:

- The dry run prices the run against `cost_cap_usd`.
- The run's pilot batch re-projects the total from measured usage. If the projection is over
  the cap, the arms in `drop_order` are dropped; if it is still over, the run stops.
- Before every batch and every direct call, recorded spend plus the estimated new work plus the
  judge's reserve must fit the cap.

## Outputs

Each run lives in `runs/<run_id>/`:

| File | Contents |
|---|---|
| `run_config.json` | pinned model IDs, each arm's exact parameters, and the SHA-256 of every frozen input |
| `config.yaml`, `tasks.yaml`, `cases.jsonl`, `cases.meta.json`, `prompts/`, `dry_run.json` | frozen copies of the inputs |
| `models_snapshot.json` | the full models-list response when the run started |
| `calls.jsonl` | one record per API call: model, parameters, prompt hash, raw response, parsed label, tokens, latency, timestamps |
| `manifest.jsonl`, `HEAD.json` | the hash chain over `calls.jsonl` |
| `state.json` | run progress, batch IDs, and the pilot's cost projection |
| `refusals.json`, `scores.json`, `final_answers.csv` | scoring |
| `diffs.csv`, `diffs_C_vs_D.csv`, `diff_summary.json` | diffs for the headline pair and the model-only pair |
| `diffs_sample_for_review.csv`, `judge_reliability.json` | the model-only review sample, with blank `rule_label`, `rule_note`, `human_verdict`, and `notes` columns, and the judge's agreement with the confirmed labels |
| `report.md`, `per_task.md`, `attribution.md`, `accuracy_by_task.png`, `diff_categories_by_task.png` | the report |
| `examples.md` | a few vetted cases, quoted verbatim or paraphrased, written per run and published with the report |

`publish` copies only the aggregate outputs and `examples.md` to `reports/<run_id>/`, plus a
README holding the chain head and the `verify` command.

## Tamper evidence

The chain covers every record in `calls.jsonl`, judge calls included:

- Each `manifest.jsonl` line holds the SHA-256 of one record and of the previous manifest line.
- The first link hashes `run_config.json`, which holds the hashes of the frozen inputs and the
  models snapshot.
- `HEAD.json` records the count and last hash, so truncating both files is detectable.

`verify` re-walks all of this offline and reports edits, deletions, reordering, truncation,
changed inputs, and unpinned model IDs.

Someone able to rewrite every file could rebuild a consistent chain. To anchor a run, publish
its head hash; the report prints it. Any model ID outside the three pinned in config is refused
when a record is written. So is a response from a model other than the one requested.

## Bring your own cases

Any corpus with one JSON object per line holding `case_id`, `task`, `input`, `gold_label`, and
`license` works without code changes:

1. Set `corpus.adapter: jsonl` and `corpus.path` in `config.yaml`.
2. Describe each task's labels, flag labels, and prompt family in the task file.
3. Add a `prompts/<family>.txt` with a `{{LABELS}}` placeholder.

## Tests

```sh
uv run pytest
```

The suite makes no network calls. It uses small synthetic fixtures, a fake client shaped like
the Anthropic SDK (covering run, resume, cap stops, batch adoption, score, diff, report, judge
reliability, publish, and verify end to end), and the real SDK on a mock transport to check
exactly what is sent.

## Data and licensing

Cases come from [LegalBench](https://huggingface.co/datasets/nguha/legalbench) at a pinned
commit. Each task's license is recorded in `data/TASKS.md`; all five tasks are CC BY 4.0 or MIT,
and the CC BY tasks require attribution in anything published from them. Sampled cases and run
outputs quote that public text, so `data/cases.jsonl` and `runs/` are gitignored and regenerate
deterministically from `config.yaml`.

Design decisions and rejected alternatives are logged in [`DECISIONS.md`](DECISIONS.md).

## Data attribution

Cases are from LegalBench ([`nguha/legalbench`](https://huggingface.co/datasets/nguha/legalbench), test split): `insurance_policy_interpretation`, `telemarketing_sales_rule` and `unfair_tos` under CC BY 4.0, `privacy_policy_qa` and `sara_entailment` under MIT, each task card linked in [`data/TASKS.md`](data/TASKS.md); the MIT license in [`LICENSE`](LICENSE) covers the harness code only, not the dataset text quoted in `reports/` and `docs/`.
