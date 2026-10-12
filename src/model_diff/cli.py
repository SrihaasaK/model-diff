"""model-diff command line."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import typer

from .config import load_config
from .data.cases import dump_json, read_cases, write_cases
from .data.tasks import load_tasks, require_approval
from .hashing import sha256_file

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Reproducible evidence of what changes when an LLM provider upgrades a model.",
)

CONFIG = typer.Option(Path("config.yaml"), "--config", "-c", help="Path to config.yaml.")


def checked_client(cfg):
    """An API client, after the startup check that every pinned model is available."""
    from .api import check_models, list_models, make_client

    client = make_client()
    typer.echo("Pinned models:")
    check_models(list_models(client), cfg, typer.echo)
    return client


@app.command()
def models(config: Path = CONFIG) -> None:
    """Confirm every pinned model ID is available to this API key and print its status."""
    checked_client(load_config(config))


@app.command("propose-tasks")
def propose_tasks(config: Path = CONFIG, out: Path = typer.Option(Path("data/TASKS.md"), help="Where to write the proposal.")) -> None:
    """Screen LegalBench, re-check licenses, and write the task proposal to data/TASKS.md."""
    from .data.propose import propose

    cfg = load_config(config)
    task_file = load_tasks(cfg.paths.tasks)
    out.write_text(propose(cfg, task_file, typer.echo), encoding="utf-8")
    typer.echo(f"\nWrote {out}.")
    if not task_file.approved:
        typer.echo(f"Review it, then set approved: true in {cfg.paths.tasks} to unlock sampling and paid runs.")


@app.command()
def sample(config: Path = CONFIG) -> None:
    """Draw cases_per_task cases per approved task with the fixed seed and write data/cases.jsonl."""
    from .data.legalbench import build_adapter
    from .data.sample import sample_cases, summarize

    cfg = load_config(config)
    task_file = load_tasks(cfg.paths.tasks)
    require_approval(task_file, cfg.paths.tasks)
    pool = build_adapter(cfg, task_file.tasks).load_pool()
    cases = sample_cases(pool, task_file.tasks, cfg.cases_per_task, cfg.seed)
    write_cases(cfg.paths.cases, cases)
    summary = summarize(cases)
    dump_json(
        cfg.paths.cases.with_name("cases.meta.json"),
        {
            "sha256": sha256_file(cfg.paths.cases),
            "seed": cfg.seed,
            "cases_per_task": cfg.cases_per_task,
            "corpus": cfg.corpus.model_dump(),
            "tasks": summary,
            # The full source split's label counts: the natural mix used to reweight stratified tasks.
            "pool": summarize(pool),
        },
    )
    for task, info in summary.items():
        labels = ", ".join(f"{label} {n}" for label, n in info["labels"].items())
        typer.echo(f"  {task:<34} {info['n']:>4}  ({labels})")
    typer.echo(f"Wrote {len(cases)} cases to {cfg.paths.cases}.")


@app.command("dry-run")
def dry_run(config: Path = CONFIG) -> None:
    """Count input tokens exactly (free), price the run, and apply the cost cap. Makes no paid call."""
    from .estimate import count_input_tokens, estimate, pilot_cases, plan_arms, render
    from .prompts import PromptBook

    cfg = load_config(config)
    task_file = load_tasks(cfg.paths.tasks)
    require_approval(task_file, cfg.paths.tasks)
    cases = read_cases(cfg.paths.cases)
    meta = json.loads(cfg.paths.cases.with_name("cases.meta.json").read_text(encoding="utf-8"))
    if meta["sha256"] != sha256_file(cfg.paths.cases):
        raise SystemExit(f"{cfg.paths.cases} changed since `model-diff sample`; re-run sample.")

    from .api import check_models, list_models, make_client

    client = make_client()
    typer.echo("Pinned models:")
    statuses = check_models(list_models(client), cfg, typer.echo)
    book = PromptBook(cfg.paths.prompts, task_file.tasks)
    counts = count_input_tokens(client, cfg, book, cases, cfg.paths.cases.with_name("token_counts.jsonl"), typer.echo)
    plans = plan_arms(cfg, book, cases, counts)
    result = estimate(cfg, plans, len(cases), len(pilot_cases(cases, cfg.run.pilot_fraction, cfg.seed)))
    result |= {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config_sha256": sha256_file(config),
        "cases_sha256": meta["sha256"],
        "prompts": book.digest(),
        "models": [s.to_dict() for s in statuses],
    }
    out = cfg.paths.cases.with_name("dry_run.json")
    dump_json(out, result)
    typer.echo("")
    typer.echo(render(result))
    typer.echo(f"\nWrote {out}.")
    if result["status"] == "over_cap":
        raise typer.Exit(code=1)


@app.command()
def run(
    config: Path = CONFIG,
    run_id: str = typer.Option(None, "--run-id", help="Resume this run instead of starting a new one."),
) -> None:
    """Execute the run: preflight, pilot batch, cost re-projection, main batch, latency probes."""
    from .api import list_models, models_snapshot
    from .prompts import PromptBook
    from .runner import Runner, check_resumable, create_run_dir

    cfg = load_config(config)
    task_file = load_tasks(cfg.paths.tasks)
    require_approval(task_file, cfg.paths.tasks)
    client = checked_client(cfg)

    if run_id:
        # A resumed run is checked against its own frozen config and verified records.
        run_dir = cfg.paths.runs / run_id
        if not run_dir.is_dir():
            raise SystemExit(f"No run directory at {run_dir}")
        check_resumable(run_dir, cfg)
        typer.echo(f"Resuming run {run_id}")
    else:
        dry_path = cfg.paths.cases.with_name("dry_run.json")
        if not dry_path.exists():
            raise SystemExit("No dry-run estimate found. Run `model-diff dry-run` first.")
        dry = json.loads(dry_path.read_text(encoding="utf-8"))
        current_book = PromptBook(cfg.paths.prompts, task_file.tasks)
        stale = [
            name
            for name, fresh in (
                ("config.yaml", dry["config_sha256"] == sha256_file(config)),
                ("cases", dry["cases_sha256"] == sha256_file(cfg.paths.cases)),
                ("prompts", dry["prompts"] == current_book.digest()),
            )
            if not fresh
        ]
        if stale:
            raise SystemExit(f"The dry-run estimate is out of date ({', '.join(stale)} changed). Re-run `model-diff dry-run`.")
        if dry["status"] == "over_cap":
            raise SystemExit("The dry-run estimate is over the cost cap; the run will not start.")
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        files = {
            "config.yaml": config,
            "tasks.yaml": cfg.paths.tasks,
            "cases.jsonl": cfg.paths.cases,
            "cases.meta.json": cfg.paths.cases.with_name("cases.meta.json"),
            "dry_run.json": dry_path,
        }
        run_dir = create_run_dir(cfg, run_id, files, current_book, models_snapshot(list_models(client)))
        typer.echo(f"Started run {run_id} in {run_dir}")

    # From here on the run uses its frozen copies of the tasks, cases, and prompts.
    frozen_tasks = load_tasks(run_dir / "tasks.yaml").tasks
    runner = Runner(cfg, client, run_dir, PromptBook(run_dir / "prompts", frozen_tasks), read_cases(run_dir / "cases.jsonl"), typer.echo)
    status = runner.execute()
    typer.echo(f"\nRun {run_id}: {status}. Recorded spend {runner.spent:.2f} USD. Chain head {runner.recorder.head}")
    if status != "complete":
        raise typer.Exit(code=2)


@app.command()
def score(run_id: str, config: Path = CONFIG) -> None:
    """Decide refusals (rules plus judge), compute per-arm and per-task metrics, write scores.json."""
    from .pipeline import score_run

    cfg = load_config(config)
    run_dir = cfg.paths.runs / run_id
    scores = score_run(run_dir, checked_client(load_config(run_dir / "config.yaml")), typer.echo)
    judge = scores["judge"]
    typer.echo(f"Judge: {judge['asked_now']} refusal checks asked now, {judge['not_judged']} not judged; "
               f"{judge['spent_usd']:.4f} USD judge spend in total.")
    typer.echo(f"Wrote refusals.json, scores.json, and final_answers.csv in {run_dir}.")


@app.command("diff")
def diff_cmd(run_id: str, config: Path = CONFIG) -> None:
    """Compare the headline arms case by case, have the judge describe each change, and attribute it."""
    from .pipeline import diff_run, headline_lines

    cfg = load_config(config)
    run_dir = cfg.paths.runs / run_id
    summary = diff_run(run_dir, checked_client(load_config(run_dir / "config.yaml")), typer.echo)
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    for line in headline_lines(scores, summary):
        typer.echo(line)
    typer.echo(f"Wrote diffs.csv, diffs_sample_for_review.csv, and diff_summary.json in {run_dir}.")


@app.command()
def report(run_id: str, config: Path = CONFIG) -> None:
    """Write report.md and its two charts from a scored and diffed run. Offline: makes no API call."""
    from .pipeline import report_run

    cfg = load_config(config)
    out = report_run(cfg.paths.runs / run_id)
    typer.echo(f"Wrote {out}, accuracy_by_task.png, and diff_categories_by_task.png.")


@app.command()
def verify(run_id: str, config: Path = CONFIG) -> None:
    """Re-walk a run's hash chain offline and report tampering or truncation."""
    from .record.chain import verify_run

    cfg = load_config(config)
    run_dir = cfg.paths.runs / run_id
    if not run_dir.is_dir():
        raise SystemExit(f"No run directory at {run_dir}")
    result = verify_run(run_dir)
    if result.ok:
        typer.echo(f"OK: {result.records} records, chain intact. Head: {result.head}")
        return
    typer.echo(f"FAILED: {len(result.problems)} problem(s) in {run_dir}")
    for problem in result.problems:
        typer.echo(f"  - {problem}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
