"""Operational hosting primitives: fencing, backpressure, circuit breakers, and checkpoints."""

from __future__ import annotations

from enum import StrEnum
from time import monotonic
from pydantic import BaseModel, ConfigDict, Field


class LeaseFence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    lease_id: str
    worker_id: str
    generation: int = Field(ge=1)
    fencing_token: int = Field(ge=1)

    def assert_newer_than(self, previous: "LeaseFence | None") -> None:
        if previous is not None and self.fencing_token <= previous.fencing_token:
            raise ValueError("stale fencing token")


class BackpressureGate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capacity: int = Field(gt=0)
    in_flight: int = Field(default=0, ge=0)

    def acquire(self) -> None:
        if self.in_flight >= self.capacity:
            raise RuntimeError("worker backpressure limit reached")
        self.in_flight += 1

    def release(self) -> None:
        self.in_flight = max(0, self.in_flight - 1)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 5, reset_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.state = CircuitState.CLOSED
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.state == CircuitState.OPEN and self.opened_at is not None:
            if monotonic() - self.opened_at >= self.reset_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def success(self) -> None:
        self.failures = 0
        self.state = CircuitState.CLOSED
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = monotonic()


class CampaignCheckpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    campaign_id: str
    sequence: int = Field(ge=0)
    state_hash: str
    journal_head_hash: str
    worker_generation: int = Field(ge=1)
