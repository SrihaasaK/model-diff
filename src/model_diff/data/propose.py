"""propose-tasks: screen LegalBench for compliance tasks and render data/TASKS.md.

The screen is a keyword filter over each task's name and instruction plus a
check that the answer space is a small categorical set. It narrows 162 tasks
to a reviewable list; the proposal itself lives in data/tasks.yaml, where every
choice carries a written justification.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import urllib.request
from collections import Counter
from statistics import mean
from typing import Callable

from ..config import Config
from .legalbench import LegalBenchAdapter
from .tasks import TaskFile

LEGALBENCH_REPO_COMMIT = "b46bf4ffae90524b2b72aaa30e7745fe9db64481"
CARD_URL = "https://raw.githubusercontent.com/HazyResearch/legalbench/{commit}/tasks/{task}/README.md"
METADATA_URL = "https://huggingface.co/datasets/{dataset}/resolve/{revision}/task_metadata.json"

DOMAIN_TERMS = re.compile(
    r"insur|tax|privacy|personal (data|information)|user information|consumer|telemarket|unfair"
    r"|loan|lender|borrower|credit|financ|bank|debt|securities|payment|data retention|third part",
    re.IGNORECASE,
)
LICENSE_LINE = re.compile(r"\*\*License\*\*:\s*(.+)")
MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8")


def screen(metadata: dict[str, dict]) -> list[str]:
    """Tasks whose name or instruction mentions a target domain and whose answer space has 2-12 labels."""
    return sorted(
        task
        for task, meta in metadata.items()
        if DOMAIN_TERMS.search(f"{task} {meta.get('instruction', '')}")
        and 2 <= len(meta.get("answer_space") or []) <= 12
    )


def card_license(task: str) -> str | None:
    """The license stated on the task's card in the LegalBench repository."""
    match = LICENSE_LINE.search(fetch_text(CARD_URL.format(commit=LEGALBENCH_REPO_COMMIT, task=task)))
    return MARKDOWN_LINK.sub(r"\1", match.group(1)).strip() if match else None


def is_noncommercial(license_text: str | None) -> bool:
    return bool(license_text and re.search(r"\bNC\b|non-?commercial", license_text, re.IGNORECASE))


def _same_license(a: str | None, b: str | None) -> bool:
    norm = lambda s: re.sub(r"[^a-z0-9.]", "", (s or "").lower())
    return norm(a) == norm(b)


def _screened_entry(task: str, task_file: TaskFile) -> dict[str, str] | None:
    digest = hashlib.sha256(task.encode("utf-8")).hexdigest()
    for entry in task_file.screened_out:
        if entry.get("match_sha256") == digest:
            return entry
        match = entry.get("match")
        if match and (task == match or (match.endswith("_") and task.startswith(match))):
            return entry
    return None


def task_stats(adapter: LegalBenchAdapter, task: str) -> dict:
    cases = [adapter.to_case(task, row) for row in adapter.load_rows(task)]
    return {
        "n": len(cases),
        "labels": Counter(c.gold_label for c in cases),
        "mean_chars": round(mean(len(c.input) for c in cases)),
    }


def render(cfg: Config, task_file: TaskFile, stats: dict[str, dict], licenses: dict[str, str | None],
           screened: list[str], today: str) -> str:
    approved = "approved" if task_file.approved else "awaiting approval"
    revision = cfg.corpus.revision or ""
    planned = {task: min(cfg.cases_per_task, stats[task]["n"]) for task in task_file.tasks}
    lines = [
        "# Proposed LegalBench tasks",
        "",
        f"Status: **{approved}** (`approved: {str(task_file.approved).lower()}` in `data/tasks.yaml`).",
        "",
        f"Source: Hugging Face `{cfg.corpus.dataset}` at commit `{revision[:12]}`, `{cfg.corpus.split}` split. "
        f"Licenses are read from each task's card in the LegalBench repository at commit "
        f"`{LEGALBENCH_REPO_COMMIT[:12]}` and were re-checked by `model-diff propose-tasks` on {today}.",
        "",
        (
            f"All {len(task_file.tasks)} proposed tasks carry licenses that permit commercial use "
            f"({', '.join(sorted({spec.license for spec in task_file.tasks.values()}))}). "
            if not any(is_noncommercial(licenses.get(t)) for t in task_file.tasks)
            else "**Some proposed tasks carry non-commercial licenses; see Details.** "
        )
        + "Tasks under non-commercial licenses were screened out because this harness will later run "
        "commercially; CC BY tasks require attribution in the write-up.",
        "",
        "## Proposed tasks",
        "",
        "| Task | Domain | Labels | Flag label(s) | Test split | Planned sample | Sampling | License |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for task, spec in task_file.tasks.items():
        flag = ", ".join(spec.positive_labels) if len(spec.positive_labels) <= 2 else "any label except Other"
        lines.append(
            f"| `{task}` | {spec.domain} | {len(spec.labels)} | {flag} | {stats[task]['n']} | "
            f"{planned[task]} | {spec.sampling} | {spec.license} |"
        )
    lines += ["", "### Justifications", ""]
    for task, spec in task_file.tasks.items():
        lines.append(f"- **`{task}`**: {spec.justification}")
    lines += ["", "### Details", ""]
    for task, spec in task_file.tasks.items():
        s = stats[task]
        label_counts = ", ".join(f"{label} {s['labels'].get(label, 0)}" for label in spec.labels)
        mapped = (
            " (dataset codes " + ", ".join(f"{k}={v}" for k, v in spec.label_map.items()) + ")"
            if spec.label_map
            else ""
        )
        fields = " + ".join(heading or column for column, heading in spec.input_fields)
        verified = "matches the task card" if _same_license(spec.license, licenses.get(task)) else (
            f"**differs from the task card ({licenses.get(task)!r}); resolve before approving**"
        )
        lines += [
            f"**`{task}`** · prompt family `{spec.family}`",
            "",
            f"- Labels{mapped}: {', '.join(spec.labels)}",
            f"- Test-split gold labels: {label_counts}",
            f"- Input: {fields}; mean {s['mean_chars']} characters",
            f"- License: [{spec.license}]({spec.license_url}), {verified}",
            "",
        ]
    total = sum(planned.values())
    lines += [
        "## Sample plan",
        "",
        f"`cases_per_task: {cfg.cases_per_task}` and `seed: {cfg.seed}` give **{total} cases**. Tasks with fewer "
        f"test cases than that are used whole. Each case runs {cfg.n_runs} times on each model, so the run makes "
        f"{total * cfg.n_runs * 2} subject calls before latency probes and judge calls. `model-diff dry-run` "
        "prices this exactly before any paid call.",
        "",
    ]
    small = [t for t in task_file.tasks if stats[t]["n"] < cfg.cases_per_task]
    if small:
        sizes = " and ".join(f"`{t}` ({stats[t]['n']} cases)" for t in small)
        lines.append(
            f"- {sizes} are used whole and are small. Per-task confidence intervals there will be wide, "
            "and per-task changes should be read as indicative."
        )
    for task, spec in task_file.tasks.items():
        if spec.sampling == "stratified":
            top_label, top_n = stats[task]["labels"].most_common(1)[0]
            share = round(100 * top_n / stats[task]["n"])
            lines.append(
                f"- `{task}` is sampled stratified, with equal shares per label, because {share}% of its "
                f"test split is `{top_label}`. Its flag rate describes the sample, not the natural mix."
            )
    unscreened = [f"`{t}`" for t in task_file.tasks if t not in screened]
    lines += [
        "- Case inputs quote public source text, which can include website names. "
        "`data/cases.jsonl` and `runs/` are gitignored and regenerate deterministically.",
        "",
        "## Screened out",
        "",
        f"The keyword screen (see `model-diff propose-tasks`) matched {len(screened)} tasks. "
        + (
            f"{', '.join(unscreened)} did not match the screen and was added by hand; its justification "
            "above gives the domain. "
            if unscreened
            else ""
        )
        + "These matches are not proposed:",
        "",
        "| Candidate | License (task card) | Reason |",
        "|---|---|---|",
    ]
    for task in screened:
        if task in task_file.tasks:
            continue
        entry = _screened_entry(task, task_file) or {"reason": "Not reviewed; add an entry to data/tasks.yaml."}
        name = entry.get("display") or f"`{task}`"
        lines.append(f"| {name} | {licenses.get(task) or 'not stated'} | {entry['reason']} |")
    return "\n".join(lines) + "\n"


def propose(cfg: Config, task_file: TaskFile, echo: Callable[[str], None] = print) -> str:
    """Screen LegalBench, verify proposed licenses, and return the TASKS.md text."""
    revision = cfg.corpus.revision
    metadata = json.loads(fetch_text(METADATA_URL.format(dataset=cfg.corpus.dataset, revision=revision)))
    screened = screen(metadata)
    echo(f"LegalBench lists {len(metadata)} tasks; the domain screen matched {len(screened)}.")

    licenses = {}
    for task in sorted(set(screened) | set(task_file.tasks)):
        licenses[task] = card_license(task)
    echo(f"\n  {'task':<72} {'labels':>6}  license")
    for task in sorted(licenses):
        n_labels = len(metadata.get(task, {}).get("answer_space") or [])
        mark = "proposed" if task in task_file.tasks else ("NC" if is_noncommercial(licenses[task]) else "")
        echo(f"  {task:<72} {n_labels:>6}  {licenses[task] or '?':<16} {mark}")

    for task, spec in task_file.tasks.items():
        if not _same_license(spec.license, licenses[task]):
            echo(f"WARNING: {task}: tasks.yaml says {spec.license!r}, task card says {licenses[task]!r}")
        if is_noncommercial(licenses[task]):
            echo(f"WARNING: {task} is under a non-commercial license: {licenses[task]}")

    adapter = LegalBenchAdapter(cfg.corpus.dataset, revision, cfg.corpus.split, task_file.tasks)
    stats = {task: task_stats(adapter, task) for task in task_file.tasks}
    return render(cfg, task_file, stats, licenses, screened, dt.date.today().isoformat())
