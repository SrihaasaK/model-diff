# model-diff

Reproducible, tamper-evident evidence of what happens to compliance-sensitive classification
outputs when an LLM provider upgrades a model. The first comparison runs Claude Sonnet 4.5
(`claude-sonnet-4-5-20250929`) against Claude Sonnet 5.5 (`claude-sonnet-5-5`) on public
LegalBench tasks in insurance, tax, privacy, and consumer protection.

## Status

Stages 1 and 2 of 8 are built: the scaffold and tests, then the dataset adapter and task
proposal. The run is paused for approval of the task list in [`data/TASKS.md`](data/TASKS.md).
Prompts, the recorder, the dry-run estimate, the paid run, scoring, diffing, reporting, and
verification are built after that approval.

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
```

`sample`, and every paid command after it, refuses to run until `approved: true` is set in
`data/tasks.yaml`.

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
