"""Monte Carlo balancing, parameter sweeps, regression thresholds, and predictive proposal ranking."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from statistics import mean, median, pstdev
from pydantic import BaseModel, ConfigDict, Field


class BalanceSample(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    outcome: str
    rounds: int = Field(ge=0)
    hp_remaining: float = Field(default=0, ge=0)
    resource_spend: float = Field(default=0, ge=0)
    action_efficiency: float = Field(default=0, ge=0)


class BalanceReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    samples: int = Field(ge=1)
    outcome_rates: dict[str, float]
    mean_rounds: float
    median_rounds: float
    stdev_rounds: float
    mean_hp_remaining: float
    mean_resource_spend: float
    mean_action_efficiency: float


ScenarioRunner = Callable[[int, dict[str, object]], BalanceSample]
AsyncScenarioRunner = Callable[[int, dict[str, object]], Awaitable[BalanceSample]]


class BalanceLab:
    @staticmethod
    def summarize(samples: list[BalanceSample]) -> BalanceReport:
        if not samples:
            raise ValueError("at least one sample is required")
        counts: dict[str, int] = {}
        for sample in samples:
            counts[sample.outcome] = counts.get(sample.outcome, 0) + 1
        rounds = [sample.rounds for sample in samples]
        return BalanceReport(
            samples=len(samples),
            outcome_rates={key: value / len(samples) for key, value in sorted(counts.items())},
            mean_rounds=mean(rounds),
            median_rounds=median(rounds),
            stdev_rounds=pstdev(rounds),
            mean_hp_remaining=mean(sample.hp_remaining for sample in samples),
            mean_resource_spend=mean(sample.resource_spend for sample in samples),
            mean_action_efficiency=mean(sample.action_efficiency for sample in samples),
        )

    def run(self, runner: ScenarioRunner, parameters: dict[str, object], *, seeds: Iterable[int]) -> BalanceReport:
        return self.summarize([runner(seed, dict(parameters)) for seed in seeds])

    async def run_async(
        self,
        runner: AsyncScenarioRunner,
        parameters: dict[str, object],
        *,
        seeds: Iterable[int],
        concurrency: int = 8,
    ) -> BalanceReport:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        semaphore = asyncio.Semaphore(concurrency)

        async def one(seed: int) -> BalanceSample:
            async with semaphore:
                return await runner(seed, dict(parameters))

        samples = await asyncio.gather(*(one(seed) for seed in seeds))
        return self.summarize(list(samples))


class RegressionThreshold(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    metric: str
    maximum_delta: float = Field(ge=0)

    def assert_within(self, baseline: float, candidate: float) -> None:
        if abs(candidate - baseline) > self.maximum_delta:
            raise AssertionError(
                f"balance regression {self.metric}: |{candidate} - {baseline}| > {self.maximum_delta}"
            )


class DirectorCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: str
    pacing_score: float
    risk: float = Field(ge=0)
    resource_pressure: float = Field(ge=0)
    report: BalanceReport


class PredictiveDirector:
    def rank(self, candidates: list[DirectorCandidate]) -> tuple[DirectorCandidate, ...]:
        def score(item: DirectorCandidate) -> tuple[float, str]:
            win_rate = item.report.outcome_rates.get("success", 0.0)
            utility = item.pacing_score + win_rate - item.risk - item.resource_pressure
            return utility, item.candidate_id

        return tuple(sorted(candidates, key=score, reverse=True))
