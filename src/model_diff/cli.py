"""model-diff command line."""

from __future__ import annotations

from pathlib import Path

import typer

from .config import load_config
from .data.cases import dump_json, write_cases
from .data.tasks import load_tasks, require_approval
from .hashing import sha256_file

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Reproducible evidence of what changes when an LLM provider upgrades a model.",
)

CONFIG = typer.Option(Path("config.yaml"), "--config", "-c", help="Path to config.yaml.")


@app.command()
def models(config: Path = CONFIG) -> None:
    """Confirm every pinned model ID is available to this API key and print its status."""
    from .api import check_models, make_client

    cfg = load_config(config)
    typer.echo("Pinned models:")
    check_models(make_client(), cfg, typer.echo)


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
        },
    )
    for task, info in summary.items():
        labels = ", ".join(f"{label} {n}" for label, n in info["labels"].items())
        typer.echo(f"  {task:<34} {info['n']:>4}  ({labels})")
    typer.echo(f"Wrote {len(cases)} cases to {cfg.paths.cases}.")


if __name__ == "__main__":
    app()
