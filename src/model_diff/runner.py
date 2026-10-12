"""model-diff run: preflight, pilot batch, cost re-projection, main batch, latency probes.

Every model call is recorded through the Recorder as soon as it returns. A run
can be resumed: requests already recorded are never re-sent, and a batch that
was already submitted is polled again rather than resubmitted. Before any
batch or direct call, the recorded spend plus the estimated cost of the work
about to start plus the judge reserve must fit the cost cap.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import platform
import shutil
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Callable

import anthropic

from .api import sdk_kwargs, with_backoff
from .config import Config, load_config
from .data.cases import Case
from .estimate import pilot_cases, probe_cases
from .hashing import sha256_file
from .prompts import PromptBook, prompt_sha256
from .record.chain import verify_run
from .record.recorder import RUN_CONFIG, ModelPinError, Recorder, repair_interrupted_append
from .record.schema import JUDGE, CallRecord, subject_key
from .score.parse import parse_response

PREFLIGHT_SYSTEM = 'Reply with the JSON object {"ok": true} and nothing else.'
PREFLIGHT_MESSAGES = [{"role": "user", "content": "Parameter check."}]
# Config fields that may change between a run's start and its resumption.
RESUMABLE_CHANGES = {"cost_cap_usd": None, "paths": None, "judge": {"budget_usd"}, "run": {"poll_interval_s"}}


class StopRun(RuntimeError):
    """A controlled stop: the run keeps its progress and can be resumed."""


class CapReached(StopRun):
    """The work about to start would take recorded spend past the cost cap."""


@dataclass(frozen=True)
class Job:
    """One request: a case under one arm's parameters, for one repeat."""

    custom_id: str
    arm: str
    case: Case
    repeat_index: int
    request: dict[str, Any]  # everything sent: the arm's parameters plus system and messages
    prompt_sha256: str

    @property
    def key(self) -> str:
        return subject_key(self.arm, self.case.case_id, self.repeat_index)

    @property
    def params(self) -> dict[str, Any]:
        return {k: v for k, v in self.request.items() if k not in ("system", "messages")}


def build_jobs(cfg: Config, book: PromptBook, cases: list[Case], arms: list[str], repeats: int) -> list[Job]:
    position = {c.case_id: i for i, c in enumerate(cases)}
    jobs = []
    for arm in arms:
        params = cfg.arm_params(arm)
        for case in cases:
            request, sha = book.request(case, params)
            for r in range(repeats):
                jobs.append(Job(f"{arm}-{r}-{position[case.case_id]:05d}", arm, case, r, request, sha))
    return jobs


def decide(arms: list[str], drop_order: list[str], cap: float, project: Callable[[list[str]], dict]) -> tuple[list[str], list[str], dict]:
    """Drop arms in order until the projected total fits the cap. Returns kept arms, dropped arms, last projection."""
    kept, dropped = list(arms), []
    projection = project(kept)
    for arm in drop_order:
        if projection["projected_total_usd"] <= cap:
            break
        if arm in kept:
            kept.remove(arm)
            dropped.append(arm)
            projection = project(kept)
    return kept, dropped, projection


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def response_text(message: Any) -> str:
    return "".join(block.text for block in message.content if block.type == "text")


def thinking_tokens(message: Any) -> int | None:
    details = getattr(message.usage, "output_tokens_details", None)
    return getattr(details, "thinking_tokens", None) if details is not None else None


def write_json(path: Path, obj: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def create_run_dir(
    cfg: Config,
    run_id: str,
    files: dict[str, Path],
    book: PromptBook,
    snapshot: dict,
) -> Path:
    """Freeze a new run: copy its inputs, store the models snapshot, and write run_config.json.

    files maps names inside the run directory to source paths; it must include
    config.yaml. Every frozen file's SHA-256 goes into run_config.json, whose own
    hash anchors the record chain.
    """
    run_dir = cfg.paths.runs / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "prompts").mkdir()
    for name, source in files.items():
        shutil.copyfile(source, run_dir / name)
    for name in book.digest():
        shutil.copyfile(book.prompts_dir / name, run_dir / "prompts" / name)
    write_json(run_dir / "models_snapshot.json", snapshot)

    frozen = sorted(files) + [f"prompts/{name}" for name in book.digest()] + ["models_snapshot.json"]
    run_config = {
        "run_id": run_id,
        "created_at": utc_now(),
        "pinned_models": sorted(cfg.pinned_model_ids()),
        "model_a": cfg.model_a,
        "model_b": cfg.model_b,
        "judge_model": cfg.judge_model,
        "arms": {arm: {"label": a.label, "params": cfg.arm_params(arm)} for arm, a in cfg.arms.items()},
        "judge_params": cfg.judge_params(),
        "headline": list(cfg.headline),
        "decomposition": cfg.decomposition.model_dump() if cfg.decomposition else None,
        "drop_order": cfg.drop_order,
        "n_runs": cfg.n_runs,
        "seed": cfg.seed,
        "cost_cap_usd": cfg.cost_cap_usd,
        "sdk_version": anthropic.__version__,
        "python_version": platform.python_version(),
        "artifacts": {name: sha256_file(run_dir / name) for name in frozen},
    }
    write_json(run_dir / RUN_CONFIG, run_config)
    return run_dir


def _comparable(cfg: Config) -> dict:
    data = cfg.model_dump(mode="json")
    for key, subkeys in RESUMABLE_CHANGES.items():
        if subkeys is None:
            data.pop(key, None)
        else:
            for sub in subkeys:
                data[key].pop(sub, None)
    return data


def check_resumable(run_dir: Path, cfg: Config) -> None:
    """Refuse to continue a run whose records fail verification or whose job-defining config changed.

    Only the cost cap, the judge budget, the poll interval, and paths may differ
    from the config frozen when the run started.
    """
    run_config = json.loads((run_dir / RUN_CONFIG).read_text(encoding="utf-8"))
    if set(run_config["pinned_models"]) != cfg.pinned_model_ids():
        raise SystemExit(
            f"Run {run_config['run_id']} pins {run_config['pinned_models']} but config.yaml pins "
            f"{sorted(cfg.pinned_model_ids())}. A different model ID in the same run is an error; start a new run."
        )
    frozen, live = _comparable(load_config(run_dir / "config.yaml")), _comparable(cfg)
    changed = sorted(k for k in set(frozen) | set(live) if frozen.get(k) != live.get(k))
    if changed:
        raise SystemExit(f"config.yaml changed since run {run_config['run_id']} started ({', '.join(changed)}); start a new run.")
    repair_interrupted_append(run_dir)
    problems = verify_run(run_dir).problems
    if problems:
        raise SystemExit("The run's records fail verification:\n  " + "\n  ".join(problems))


class Runner:
    def __init__(
        self,
        cfg: Config,
        client: Any,
        run_dir: Path,
        book: PromptBook,
        cases: list[Case],
        echo: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cfg = cfg
        self.client = client
        self.run_dir = run_dir
        self.book = book
        self.cases = cases
        self.echo = echo
        self.sleep = sleep
        self.recorder = Recorder(run_dir)
        self.state_path = run_dir / "state.json"
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self.state = {"status": "started", "batches": {}, "kept_arms": list(cfg.arms), "dropped_arms": []}
        self.spent = sum(self.cost(r) for r in self.recorder.records)

    # -- bookkeeping -------------------------------------------------------

    def save_state(self) -> None:
        write_json(self.state_path, self.state)

    def cost(self, rec: CallRecord) -> float:
        return self.cfg.cost_usd(rec.model_id, rec.input_tokens, rec.output_tokens, batch=rec.batch_id is not None)

    def done(self, kind: str) -> set[str]:
        return {r.subject_key() for r in self.recorder.records if r.kind == kind and r.error is None}

    def append(self, record: CallRecord) -> None:
        self.recorder.append(record)
        self.spent += self.cost(record)

    def judge_reserve(self) -> float:
        judge_spent = sum(self.cost(r) for r in self.recorder.records if r.arm == JUDGE)
        return max(0.0, self.cfg.judge.budget_usd - judge_spent)

    def call_cost(self, arm: str, batch: bool) -> float:
        """Expected cost of one call in an arm: measured from its records, else the dry-run planning numbers."""
        recs = [r for r in self.recorder.records if r.arm == arm and r.kind in ("subject", "latency_probe") and r.error is None]
        model = self.cfg.arm_model(arm)
        if recs:
            return mean(self.cfg.cost_usd(model, r.input_tokens, r.output_tokens, batch=batch) for r in recs)
        arm_cfg = self.cfg.arms[arm]
        out = self.cfg.run.expected_output_tokens + (self.cfg.run.planning_thinking_tokens if arm_cfg.thinking_expected else 0)
        return self.cfg.cost_usd(model, 1000, out, batch=batch)

    def guard(self, jobs: list[Job], batch: bool) -> None:
        """Stop before starting work that would take spend plus the judge reserve past the cap."""
        estimate = sum(self.call_cost(j.arm, batch) for j in jobs)
        if self.spent + estimate + self.judge_reserve() > self.cfg.cost_cap_usd:
            raise CapReached(
                f"{len(jobs)} {'batched' if batch else 'direct'} calls (about {estimate:.2f} USD) on top of "
                f"{self.spent:.2f} USD spent and a {self.judge_reserve():.2f} USD judge reserve would pass the "
                f"{self.cfg.cost_cap_usd:.2f} USD cap"
            )

    def make_record(self, job: Job, kind: str, message: Any, latency_ms: float | None,
                    request_id: str | None, batch_id: str | None = None) -> CallRecord:
        text = response_text(message)
        labels = self.book.tasks[job.case.task].labels if job.case.task in self.book.tasks else None
        parsed = parse_response(text, labels) if labels else None
        stop_details = getattr(message, "stop_details", None)
        return CallRecord(
            run_id=self.recorder.run_id,
            case_id=job.case.case_id,
            task=job.case.task,
            model_id=job.params["model"],
            params=job.params,
            prompt_sha256=job.prompt_sha256,
            request_id=request_id,
            raw_response=text,
            parsed_label=parsed.label if parsed else None,
            parse_ok=parsed.parse_ok if parsed else False,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_ms=latency_ms,
            timestamp=utc_now(),
            sdk_version=anthropic.__version__,
            repeat_index=job.repeat_index,
            arm=job.arm,
            kind=kind,
            format_ok=parsed.format_ok if parsed else False,
            thinking_tokens=thinking_tokens(message),
            stop_reason=message.stop_reason,
            stop_details=stop_details.model_dump() if stop_details is not None else None,
            message_id=message.id,
            response_model=message.model,
            batch_id=batch_id,
            custom_id=job.custom_id if batch_id else None,
        )

    def error_record(self, job: Job, kind: str, exc: Exception) -> CallRecord:
        return CallRecord(
            run_id=self.recorder.run_id, case_id=job.case.case_id, task=job.case.task,
            model_id=job.params["model"], params=job.params, prompt_sha256=job.prompt_sha256,
            request_id=getattr(exc, "request_id", None), raw_response="", parsed_label=None, parse_ok=False,
            input_tokens=0, output_tokens=0, latency_ms=None, timestamp=utc_now(),
            sdk_version=anthropic.__version__, repeat_index=job.repeat_index, arm=job.arm, kind=kind,
            error=f"{type(exc).__name__}: {exc}",
        )

    # -- calls ---------------------------------------------------------------

    def call_direct(self, request: dict[str, Any]) -> tuple[Any, float]:
        """One Messages call with retries; latency covers only the attempt that succeeded."""
        timing: dict[str, float] = {}

        def attempt() -> Any:
            start = time.perf_counter()
            message = self.client.messages.create(**sdk_kwargs(request))
            timing["ms"] = (time.perf_counter() - start) * 1000
            return message

        message = with_backoff(attempt, echo=self.echo)
        return message, timing["ms"]

    def run_sequential(self, jobs: list[Job], kind: str) -> int:
        """Send jobs one at a time; returns how many failed permanently."""
        done = self.done(kind)
        todo = [j for j in jobs if j.key not in done]
        if todo:
            self.guard(todo, batch=False)
        failures = 0
        for job in todo:
            self.guard([job], batch=False)
            try:
                message, latency = self.call_direct(job.request)
            except anthropic.APIError as exc:
                self.append(self.error_record(job, kind, exc))
                failures += 1
                continue
            self.append(self.make_record(job, kind, message, latency, getattr(message, "_request_id", None)))
        return failures

    def wait(self, batch_id: str) -> Any:
        while True:
            batch = with_backoff(lambda: self.client.messages.batches.retrieve(batch_id), echo=self.echo)
            counts = batch.request_counts
            self.echo(
                f"  {batch_id}: {batch.processing_status}; processing {counts.processing}, "
                f"succeeded {counts.succeeded}, errored {counts.errored}, expired {counts.expired}"
            )
            if batch.processing_status == "ended":
                return batch
            self.sleep(self.cfg.run.poll_interval_s)

    def find_submitted(self, intent: dict) -> str | None:
        """A batch created since the recorded intent with the intended request count, if one exists."""
        since = dt.datetime.fromisoformat(intent["at"]) - dt.timedelta(minutes=2)
        for batch in with_backoff(lambda: list(self.client.messages.batches.list(limit=50)), echo=self.echo):
            counts = batch.request_counts
            total = counts.processing + counts.succeeded + counts.errored + counts.canceled + counts.expired
            if batch.created_at >= since and total == intent["requests"]:
                return batch.id
        return None

    def submit(self, name: str, pending: list[Job]) -> str | None:
        """Create the batch once. The intent is saved first, and creation is never retried blindly:
        if the call fails or a previous attempt was interrupted, an already-created batch is adopted."""
        intent = self.state.setdefault("batch_intents", {}).get(name)
        if intent is not None:
            found = self.find_submitted(intent)
            if found:
                self.echo(f"Adopting the {name} batch {found}, created by an interrupted earlier attempt.")
                return found
        self.guard(pending, batch=True)
        self.state["batch_intents"][name] = {"at": utc_now(), "requests": len(pending)}
        self.save_state()
        requests = [{"custom_id": j.custom_id, "params": j.request} for j in pending]
        try:
            return self.client.messages.batches.create(requests=requests).id
        except anthropic.APIError as exc:
            found = self.find_submitted(self.state["batch_intents"][name])
            if found:
                self.echo(f"The create call reported {type(exc).__name__}, but batch {found} exists; adopting it.")
                return found
            self.echo(f"The {name} batch could not be created ({type(exc).__name__}); using direct calls.")
            self.state.setdefault("batch_fallbacks", {})[name] = f"{type(exc).__name__}: {exc}"
            self.save_state()
            return None

    def run_batch(self, name: str, jobs: list[Job]) -> list[Job]:
        """Run jobs as one batch (or resume the one already submitted). Returns jobs still unrecorded."""
        pending = [j for j in jobs if j.key not in self.done("subject")]
        batch_id = self.state["batches"].get(name)
        if batch_id is None:
            if not pending or not self.cfg.run.use_batch:
                return pending
            batch_id = self.submit(name, pending)
            if batch_id is None:
                return pending
            self.state["batches"][name] = batch_id
            self.save_state()
            self.echo(f"Submitted the {name} batch {batch_id}: {len(pending)} requests.")

        self.wait(batch_id)
        by_custom_id = {j.custom_id: j for j in jobs}
        done = self.done("subject")
        outcomes: Counter[str] = Counter()
        results = with_backoff(lambda: list(self.client.messages.batches.results(batch_id)), echo=self.echo)
        for result in results:
            job = by_custom_id.get(result.custom_id)
            outcomes[result.result.type] += 1
            if job is None or job.key in done or result.result.type != "succeeded":
                continue
            self.append(self.make_record(job, "subject", result.result.message, None, None, batch_id))
            done.add(job.key)
        self.state.setdefault("batch_outcomes", {})[name] = dict(outcomes)
        self.save_state()
        return [j for j in jobs if j.key not in done]

    def preflight(self, arms: list[str]) -> None:
        """One minimal request per arm with its exact parameters, before any batch."""
        done = {r.arm for r in self.recorder.records if r.kind == "preflight" and r.error is None}
        sha = prompt_sha256(PREFLIGHT_SYSTEM, PREFLIGHT_MESSAGES)
        case = Case(case_id="preflight", task="preflight", input="", gold_label="", license="")
        for arm in arms:
            if arm in done:
                continue
            request = {**self.cfg.arm_params(arm), "system": PREFLIGHT_SYSTEM, "messages": PREFLIGHT_MESSAGES}
            job = Job(f"preflight-{arm}", arm, case, 0, request, sha)
            try:
                message, latency = self.call_direct(request)
            except anthropic.APIError as exc:
                self.append(self.error_record(job, "preflight", exc))
                raise StopRun(f"preflight failed for arm {arm}: {type(exc).__name__}: {exc}") from exc
            self.append(self.make_record(job, "preflight", message, latency, getattr(message, "_request_id", None)))
            self.echo(f"  preflight {arm}: ok ({message.model})")

    # -- cost projection ---------------------------------------------------

    def projection(self, arms: list[str], jobs: list[Job], probes: list[Job]) -> dict:
        """Recorded spend plus the remaining work, priced from each arm's measured pilot usage."""
        subject = [r for r in self.recorder.records if r.kind == "subject" and r.error is None]
        done, probes_done = self.done("subject"), self.done("latency_probe")
        per_arm = {}
        remaining_total = 0.0
        for arm in arms:
            recs = [r for r in subject if r.arm == arm]
            if not recs:
                raise StopRun(f"arm {arm} has no successful pilot calls to project its cost from")
            batch_cost = lambda r: self.cfg.cost_usd(r.model_id, r.input_tokens, r.output_tokens, batch=True)
            by_task: dict[str, list[float]] = defaultdict(list)
            for r in recs:
                by_task[r.task].append(batch_cost(r))
            overall = mean(batch_cost(r) for r in recs)
            pending = [j for j in jobs if j.arm == arm and j.key not in done]
            pending_probes = [p for p in probes if p.arm == arm and p.key not in probes_done]
            batch_usd = sum(mean(by_task[j.case.task]) if by_task.get(j.case.task) else overall for j in pending)
            probe_usd = len(pending_probes) * overall / self.cfg.pricing.batch_discount
            thinking = [r.thinking_tokens for r in recs if r.thinking_tokens is not None]
            per_arm[arm] = {
                "pilot_calls": len(recs),
                "mean_input_tokens": mean(r.input_tokens for r in recs),
                "mean_output_tokens": mean(r.output_tokens for r in recs),
                "mean_thinking_tokens": mean(thinking) if thinking else None,
                "remaining_calls": len(pending) + len(pending_probes),
                "remaining_usd": batch_usd + probe_usd,
            }
            remaining_total += batch_usd + probe_usd
        reserve = self.judge_reserve()
        return {
            "spent_usd": self.spent,
            "arms": per_arm,
            "judge_reserve_usd": reserve,
            "projected_total_usd": self.spent + remaining_total + reserve,
            "cap_usd": self.cfg.cost_cap_usd,
        }

    # -- the run -------------------------------------------------------------

    def probe_jobs(self, arms: list[str]) -> list[Job]:
        return build_jobs(self.cfg, self.book, probe_cases(self.cases, self.cfg.run.latency_probe_cases), arms, 1)

    def execute(self) -> str:
        """Advance the run as far as the cap allows. Returns the phase reached or why it stopped."""
        with open(self.run_dir / ".run.lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit(f"Another process is running {self.run_dir.name}.") from None
            try:
                self.state.pop("stopped", None)
                return self._advance()
            except StopRun as exc:
                return self._stop("stopped_cap_reached" if isinstance(exc, CapReached) else "stopped", str(exc))
            except ModelPinError as exc:
                return self._stop("stopped_model_mismatch", str(exc))
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _stop(self, outcome: str, reason: str) -> str:
        self.state["stopped"] = {"outcome": outcome, "reason": reason, "at": utc_now()}
        self.save_state()
        self.echo(f"Stopped ({outcome}): {reason}.")
        return outcome

    def _advance(self) -> str:
        cfg = self.cfg
        all_arms = list(cfg.arms)
        jobs = build_jobs(cfg, self.book, self.cases, all_arms, cfg.n_runs)

        if self.state["status"] == "started":
            self.echo("Preflight:")
            self.preflight(all_arms)
            pilot_ids = {c.case_id for c in pilot_cases(self.cases, cfg.run.pilot_fraction, cfg.seed)}
            pilot = [j for j in jobs if j.case.case_id in pilot_ids]
            self.run_sequential(self.run_batch("pilot", pilot), "subject")
            self.state["status"] = "pilot_done"
            self.save_state()

        if self.state["status"] in ("pilot_done", "stopped_over_cap"):
            kept, dropped, projection = decide(
                all_arms, cfg.drop_order, cfg.cost_cap_usd,
                lambda arms: self.projection(arms, jobs, self.probe_jobs(arms)),
            )
            within = projection["projected_total_usd"] <= cfg.cost_cap_usd
            self.state.update(kept_arms=kept, dropped_arms=dropped, projection=projection)
            self.state["status"] = "approved_by_projection" if within else "stopped_over_cap"
            self.save_state()
            self.echo(
                f"Pilot projection: {projection['projected_total_usd']:.2f} USD for arms {', '.join(kept)} "
                f"(cap {cfg.cost_cap_usd:.2f}; spent so far {projection['spent_usd']:.2f})."
            )
            if dropped:
                self.echo(f"Dropped arm(s) {', '.join(dropped)} to fit the cap.")
            if not within:
                self.echo("The projection exceeds the cap even after dropping arms. Stopping before further spending.")
                return "stopped_over_cap"

        kept = self.state["kept_arms"]
        if self.state["status"] == "approved_by_projection":
            main = [j for j in jobs if j.arm in kept]
            self.run_sequential(self.run_batch("main", main), "subject")
            self.state["status"] = "batch_done"
            self.save_state()

        if self.state["status"] == "batch_done":
            self.echo("Latency probes:")
            self.run_sequential(self.probe_jobs(kept), "latency_probe")
            self.state["status"] = "complete"
            self.save_state()
        return self.state["status"]
