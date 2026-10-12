"""Load and validate config.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

ModelRole = Literal["model_a", "model_b"]


class ArmConfig(BaseModel):
    model: ModelRole
    label: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    thinking_expected: bool = False  # cost planning only: the arm's output includes thinking tokens


class Decomposition(BaseModel):
    path: list[str]  # arms, each step changing one factor
    factors: list[str]  # the factor each step changes

    @model_validator(mode="after")
    def _one_factor_per_step(self) -> "Decomposition":
        if len(self.factors) != len(self.path) - 1:
            raise ValueError("decomposition needs exactly one factor per step along the path")
        return self


class JudgeConfig(BaseModel):
    max_tokens: int = 300
    overrides: dict[str, Any] = Field(default_factory=dict)
    budget_usd: float = 1.0


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
    pilot_fraction: float = Field(default=0.05, gt=0, le=1)
    latency_probe_cases: int = 10
    expected_output_tokens: int = 100
    planning_thinking_tokens: int = 1000
    thinking_scenarios: list[int] = Field(default_factory=lambda: [0, 500, 1000, 2000])


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
    arms: dict[str, ArmConfig]
    headline: tuple[str, str]
    decomposition: Decomposition | None = None
    drop_order: list[str] = Field(default_factory=list)
    judge: JudgeConfig = JudgeConfig()
    corpus: CorpusConfig
    paths: PathsConfig = PathsConfig()
    run: RunSettings = RunSettings()
    pricing: PricingConfig

    @model_validator(mode="after")
    def _consistent(self) -> "Config":
        bad_names = [a for a in self.arms if not re.fullmatch(r"[A-Za-z0-9]{1,8}", a)]
        if bad_names:
            raise ValueError(f"arm names must be 1-8 letters or digits: {bad_names}")
        referenced = set(self.headline) | set(self.drop_order)
        if self.decomposition:
            referenced |= set(self.decomposition.path)
        unknown = referenced - set(self.arms)
        if unknown:
            raise ValueError(f"unknown arms referenced: {sorted(unknown)}")
        if set(self.headline) & set(self.drop_order):
            raise ValueError("headline arms cannot be in drop_order")
        missing = [m for m in self.pinned_model_ids() if m not in self.pricing.models]
        if missing:
            raise ValueError(f"pricing.models has no entry for: {', '.join(sorted(missing))}")
        if self.corpus.adapter == "jsonl" and not self.corpus.path:
            raise ValueError("corpus.path is required when corpus.adapter is 'jsonl'")
        return self

    def pinned_model_ids(self) -> set[str]:
        return {self.model_a, self.model_b, self.judge_model}

    def arm_model(self, arm: str) -> str:
        return self.model_a if self.arms[arm].model == "model_a" else self.model_b

    def arm_params(self, arm: str) -> dict[str, Any]:
        """Parameters sent with every request in this arm, excluding prompts.

        Shared parameters come first; the arm's overrides replace them, and a
        null override removes the parameter entirely.
        """
        params: dict[str, Any] = {"max_tokens": self.max_tokens, "temperature": self.temperature}
        _apply(params, self.arms[arm].overrides)
        return {"model": self.arm_model(arm), **params}

    def judge_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"max_tokens": self.judge.max_tokens}
        _apply(params, self.judge.overrides)
        return {"model": self.judge_model, **params}

    def cost_usd(self, model_id: str, input_tokens: float, output_tokens: float, batch: bool) -> float:
        price = self.pricing.models[model_id]
        factor = self.pricing.batch_discount if batch else 1.0
        return factor * (input_tokens * price.input + output_tokens * price.output) / 1_000_000


def _apply(params: dict[str, Any], overrides: dict[str, Any]) -> None:
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
        else:
            params[key] = value


def load_config(path: Path = Path("config.yaml")) -> Config:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Config.model_validate(raw)
