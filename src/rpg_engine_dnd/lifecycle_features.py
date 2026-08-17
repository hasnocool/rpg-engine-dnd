"""Ruleset-neutral feature grants, resources, prerequisites, choices, and progression."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class GrantKind(StrEnum):
    MODIFIER = "modifier"
    RULE = "rule"
    ACTION = "action"
    RESOURCE = "resource"


class Prerequisite(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    minimum: int | float | None = None
    equals: object | None = None

    def met(self, facts: dict[str, object]) -> bool:
        value = facts.get(self.key)
        if self.equals is not None and value != self.equals:
            return False
        if self.minimum is not None:
            if not isinstance(value, (int, float)) or value < self.minimum:
                return False
        return value is not None


class FeatureGrant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: GrantKind
    grant_id: str
    payload: dict[str, object] = Field(default_factory=dict)


class FeatureDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    feature_id: str
    prerequisites: tuple[Prerequisite, ...] = ()
    grants: tuple[FeatureGrant, ...] = ()
    choice_group: str | None = None

    def available(self, facts: dict[str, object]) -> bool:
        return all(requirement.met(facts) for requirement in self.prerequisites)


class ResourcePool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: str
    current: int = Field(ge=0)
    maximum: int = Field(ge=0)
    short_rest_recovery: int = Field(default=0, ge=0)
    long_rest_recovery: int | None = Field(default=None, ge=0)

    def spend(self, amount: int = 1) -> None:
        if amount < 1 or amount > self.current:
            raise ValueError("invalid resource spend")
        self.current -= amount

    def recover(self, *, long_rest: bool = False) -> None:
        amount = self.long_rest_recovery if long_rest else self.short_rest_recovery
        if long_rest and amount is None:
            self.current = self.maximum
        else:
            self.current = min(self.maximum, self.current + int(amount or 0))


class ProgressionStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    level: int = Field(ge=1)
    feature_ids: tuple[str, ...] = ()
    resource_maximums: dict[str, int] = Field(default_factory=dict)


class ProgressionTable(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    progression_id: str
    steps: tuple[ProgressionStep, ...]

    def through(self, level: int) -> tuple[ProgressionStep, ...]:
        return tuple(step for step in self.steps if step.level <= level)
