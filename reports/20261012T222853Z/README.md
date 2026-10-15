# Run 20261012T222853Z

Aggregate results of one model-diff run. Apart from `examples.md`, which quotes a few vetted public cases and their model responses, these files hold no case text and no model responses; the full run
directory, which quotes the public source text, stays with the author.

Chain head: `142a627cd7aa27b7e0f87087409832a9d23ece4c14d7537b6a82bef962f1c151` (10152 recorded API calls).

`scores.json` carries the head at scoring time, `b718cc49…03ba3`, recorded before the 30 review-sample judge calls (DECISIONS.md D30), which do not enter the scores; `HEAD.json` holds the final head above.

To anchor the run, compare this head with the one `verify` prints from the full run directory:

```sh
uv run model-diff verify 20261012T222853Z
```

`verify` re-walks the SHA-256 chain over every recorded call, checks each frozen input against the hashes in
`run_config.json`, and reports any edit, deletion, reordering, or truncation.

Files:

- `report.md`
- `per_task.md`
- `attribution.md`
- `examples.md`
- `accuracy_by_task.png`
- `diff_categories_by_task.png`
- `scores.json`
- `diff_summary.json`
- `run_config.json`
- `models_snapshot.json`
- `HEAD.json`
