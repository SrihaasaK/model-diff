"""Load and validate config.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

SubjectRole = Literal["model_a", "model_b"]
SUBJECT_ROLES: tuple[SubjectRole, ...] = ("model_a", "model_b")


class JudgeConfig(BaseModel):
    temperature: float = 0
    max_tokens: int = 300
    budget_usd: float = 2.0


class CorpusConfig(BaseModel):
    adapter: Literal["legalbench", "jsonl"] = "legalbench"
    path: str | None = None
    dataset: str = "nguha/legalbench"
    revision: str | None = None
    split: str = "test"


class PathsConfig(BaseModel):
    tasks: Path = Path("data/tasks.yaml")
    cases: Path = Path("data/cases.jsonl")
    prompts: Path = Path("prompts")
    runs: Path = Path("runs")


class RunSettings(BaseModel):
    use_batch: bool = True
    poll_interval_s: int = 60
    latency_probe_cases: int = 10
    expected_output_tokens: int = 160


class Price(BaseModel):
    input: float
    output: float


class PricingConfig(BaseModel):
    batch_discount: float = 0.5
    models: dict[str, Price]


class Config(BaseModel):
    model_a: str
    model_b: str
    judge_model: str
    temperature: float = 0
    max_tokens: int
    n_runs: int = Field(default=3, ge=1)
    seed: int = 42
    cases_per_task: int = Field(ge=1)
    cost_cap_usd: float = Field(gt=0)
    overrides: dict[SubjectRole, dict[str, Any]] = Field(default_factory=dict)
    judge: JudgeConfig = JudgeConfig()
    corpus: CorpusConfig
    paths: PathsConfig = PathsConfig()
    run: RunSettings = RunSettings()
    pricing: PricingConfig

    @model_validator(mode="after")
    def _every_model_has_a_price(self) -> "Config":
        missing = [m for m in self.pinned_model_ids() if m not in self.pricing.models]
        if missing:
            raise ValueError(f"pricing.models has no entry for: {', '.join(sorted(missing))}")
        if self.corpus.adapter == "jsonl" and not self.corpus.path:
            raise ValueError("corpus.path is required when corpus.adapter is 'jsonl'")
        return self

    def model_id(self, role: SubjectRole) -> str:
        return self.model_a if role == "model_a" else self.model_b

    def pinned_model_ids(self) -> set[str]:
        return {self.model_a, self.model_b, self.judge_model}

    def request_params(self, role: SubjectRole) -> dict[str, Any]:
        """Parameters sent with every subject request for this role, excluding prompts.

        Shared parameters come first; the role's overrides replace them, and a
        null override removes the parameter entirely.
        """
        params: dict[str, Any] = {"max_tokens": self.max_tokens, "temperature": self.temperature}
        for key, value in self.overrides.get(role, {}).items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        return {"model": self.model_id(role), **params}

    def judge_params(self) -> dict[str, Any]:
        return {
            "model": self.judge_model,
            "max_tokens": self.judge.max_tokens,
            "temperature": self.judge.temperature,
        }

    def cost_usd(self, model_id: str, input_tokens: int, output_tokens: int, batch: bool) -> float:
        price = self.pricing.models[model_id]
        factor = self.pricing.batch_discount if batch else 1.0
        return factor * (input_tokens * price.input + output_tokens * price.output) / 1_000_000


def load_config(path: Path = Path("config.yaml")) -> Config:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Config.model_validate(raw)
