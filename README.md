# model-diff

Reproducible, tamper-evident evidence of what happens to compliance-sensitive classification
outputs when an LLM provider upgrades a model. The first comparison runs Claude Sonnet 4.5
(`claude-sonnet-4-5-20250929`) against Claude Sonnet 5.5 (`claude-sonnet-5-5`) on public
LegalBench tasks in insurance, tax, privacy, and consumer protection.

## Status

Stages 1 to 4 of 8 are built: the scaffold and tests, the dataset adapter and approved task list
([`data/TASKS.md`](data/TASKS.md)), prompts and the hash-chained recorder, and the dry-run
estimate. The run is paused for approval of that estimate. The paid run, scoring, diffing, and
reporting are built after it.

The comparison has four arms (see `config.yaml` and `DECISIONS.md` D12): A is Sonnet 4.5 at
temperature 0, and B is Sonnet 5.5 at its API defaults; these two form the headline comparison.
C (Sonnet 4.5 at temperature 1.0) and D (Sonnet 5.5 with thinking off) are controls. They
attribute the A-to-B change to temperature, model, and thinking.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
echo 'ANTHROPIC_API_KEY=...' > .env   # gitignored; read only by the harness
uv run model-diff models              # confirm the pinned model IDs are available
```

## Commands available now

```sh
uv run model-diff models           # list pinned model IDs with lifecycle status (free API call)
uv run model-diff propose-tasks    # screen LegalBench, re-check licenses, write data/TASKS.md
uv run model-diff sample           # after approval: seeded sample to data/cases.jsonl
uv run model-diff dry-run          # exact input tokens (free), expected cost, cap decision
uv run model-diff verify <run_id>  # re-walk a run's hash chain offline; reports tamper or truncation
```

`sample`, and every paid command after it, refuses to run until `approved: true` is set in
`data/tasks.yaml`. `dry-run` makes no paid call: it counts tokens with the free token-counting
endpoint and writes `data/dry_run.json`.

## Tests

```sh
uv run pytest
```

Tests use small synthetic fixtures in `tests/fixtures/` and make no network calls.

## Bringing your own cases

Any corpus with one JSON object per line holding `case_id`, `task`, `input`, `gold_label`, and
`license` works without code changes. Set `corpus.adapter: jsonl` and `corpus.path` in
`config.yaml`, and describe each task's labels and prompt family in the task file.

## Data and licensing

Cases come from [LegalBench](https://huggingface.co/datasets/nguha/legalbench) at a pinned
commit. Each task's license is recorded in `data/TASKS.md`. All proposed tasks are CC BY 4.0
or MIT; CC BY tasks require attribution in anything published from them. Sampled cases and run
outputs quote that public text, so `data/cases.jsonl` and `runs/` are gitignored and regenerate
deterministically from `config.yaml`.

Design decisions and rejected alternatives are logged in [`DECISIONS.md`](DECISIONS.md).
