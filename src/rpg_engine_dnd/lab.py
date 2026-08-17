"""v2.1 deterministic simulation lab with bounded async concurrency and comparisons."""

from __future__ import annotations

import asyncio
import statistics
from collections import Counter
from collections.abc import Callable
from pydantic import BaseModel, ConfigDict, Field


class ScenarioSample(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    seed: int
    outcome: str
    metric: float
    event_count: int = Field(ge=0)


class MetricSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    count: int = Field(ge=0)
    mean: float
    median: float
    stdev: float
    minimum: float
    maximum: float
    p10: float
    p90: float


class LabReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    seeds: tuple[int, ...]
    retained_samples: tuple[ScenarioSample, ...] = ()
    summary: MetricSummary
    outcome_rates: dict[str, float]
    event_count_total: int = Field(ge=0)


class ReportDelta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mean_delta: float
    median_delta: float
    outcome_rate_delta: dict[str, float]


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * percentile
    low = int(index)
    high = min(len(ordered) - 1, low + 1)
    weight = index - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


class SimulationLab:
    def __init__(self, *, concurrency: int = 4) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        self.concurrency = concurrency

    @staticmethod
    def seed_matrix(root_seed: int, count: int) -> tuple[int, ...]:
        if count < 1:
            raise ValueError("count must be positive")
        return tuple(root_seed + index * 1_000_003 for index in range(count))

    async def run(
        self,
        seeds: tuple[int, ...],
        scenario: Callable[[int], ScenarioSample],
        *,
        retain_samples: bool = True,
    ) -> LabReport:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def one(seed: int) -> ScenarioSample:
            async with semaphore:
                return await asyncio.to_thread(scenario, seed)

        samples = await asyncio.gather(*(one(seed) for seed in seeds))
        values = [sample.metric for sample in samples]
        counts = Counter(sample.outcome for sample in samples)
        total = len(samples)
        summary = MetricSummary(
            count=total,
            mean=statistics.fmean(values) if values else 0.0,
            median=statistics.median(values) if values else 0.0,
            stdev=statistics.pstdev(values) if len(values) > 1 else 0.0,
            minimum=min(values, default=0.0),
            maximum=max(values, default=0.0),
            p10=_percentile(values, 0.10),
            p90=_percentile(values, 0.90),
        )
        rates = {key: value / total for key, value in sorted(counts.items())} if total else {}
        return LabReport(
            seeds=seeds,
            retained_samples=tuple(samples) if retain_samples else (),
            summary=summary,
            outcome_rates=rates,
            event_count_total=sum(sample.event_count for sample in samples),
        )

    @staticmethod
    def compare(baseline: LabReport, candidate: LabReport) -> ReportDelta:
        keys = set(baseline.outcome_rates) | set(candidate.outcome_rates)
        return ReportDelta(
            mean_delta=candidate.summary.mean - baseline.summary.mean,
            median_delta=candidate.summary.median - baseline.summary.median,
            outcome_rate_delta={
                key: candidate.outcome_rates.get(key, 0.0) - baseline.outcome_rates.get(key, 0.0)
                for key in sorted(keys)
            },
        )
