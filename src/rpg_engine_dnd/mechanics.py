"""General modifier algebra, deterministic effects, and ordered reaction windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModifierOperation(StrEnum):
    ADD = "add"
    MULTIPLY = "multiply"
    SET = "set"
    MIN = "min"
    MAX = "max"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"
    CANCEL = "cancel"
    REPLACE = "replace"


class Modifier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    modifier_id: str
    source: str
    target: str
    scope: str
    operation: ModifierOperation
    value: float | int | str | None = None
    priority: int = 0
    stacking_group: str | None = None
    duration_ticks: int | None = Field(default=None, ge=0)
    condition: str | None = None


class ModifierResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    value: float
    advantage: int = Field(default=0, ge=-1, le=1)
    cancelled: bool = False
    applied_ids: tuple[str, ...] = ()


class ModifierResolver:
    """Resolve modifiers deterministically with one winner per stacking group."""

    def resolve(self, base: float, modifiers: list[Modifier]) -> ModifierResolution:
        selected: list[Modifier] = []
        grouped: dict[str, Modifier] = {}
        for modifier in modifiers:
            if modifier.stacking_group is None:
                selected.append(modifier)
                continue
            current = grouped.get(modifier.stacking_group)
            candidate_key = (modifier.priority, modifier.modifier_id)
            current_key = (current.priority, current.modifier_id) if current else None
            if current is None or candidate_key > current_key:
                grouped[modifier.stacking_group] = modifier
        selected.extend(grouped.values())
        selected.sort(key=lambda item: (item.priority, item.modifier_id))

        value = float(base)
        advantage = 0
        cancelled = False
        applied: list[str] = []
        for modifier in selected:
            applied.append(modifier.modifier_id)
            op = modifier.operation
            if op == ModifierOperation.ADD:
                value += float(modifier.value or 0)
            elif op == ModifierOperation.MULTIPLY:
                value *= float(modifier.value if modifier.value is not None else 1)
            elif op in {ModifierOperation.SET, ModifierOperation.REPLACE}:
                value = float(modifier.value or 0)
            elif op == ModifierOperation.MIN:
                value = min(value, float(modifier.value or 0))
            elif op == ModifierOperation.MAX:
                value = max(value, float(modifier.value or 0))
            elif op == ModifierOperation.ADVANTAGE:
                advantage = min(1, advantage + 1)
            elif op == ModifierOperation.DISADVANTAGE:
                advantage = max(-1, advantage - 1)
            elif op == ModifierOperation.CANCEL:
                cancelled = True
        return ModifierResolution(
            value=value,
            advantage=advantage,
            cancelled=cancelled,
            applied_ids=tuple(applied),
        )


class RuntimeEffect(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    effect_id: str
    source_id: str
    target_id: str | None = None
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


class ReactionChoice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reaction_id: str
    actor_id: str
    action_kind: str
    priority: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class ReactionWindow:
    window_id: str
    trigger: str
    opened_sequence: int
    expires_sequence: int | None = None
    eligible_actors: frozenset[str] = frozenset()
    choices: list[ReactionChoice] = field(default_factory=list)
    closed: bool = False

    def offer(self, choice: ReactionChoice) -> None:
        if self.closed:
            raise ValueError("reaction window is closed")
        if self.eligible_actors and choice.actor_id not in self.eligible_actors:
            raise ValueError("actor is not eligible for this reaction window")
        if any(existing.reaction_id == choice.reaction_id for existing in self.choices):
            return
        self.choices.append(choice)

    def resolve(self) -> tuple[ReactionChoice, ...]:
        self.closed = True
        return tuple(sorted(self.choices, key=lambda item: (-item.priority, item.actor_id, item.reaction_id)))


class ReactionStack:
    def __init__(self) -> None:
        self._windows: list[ReactionWindow] = []

    def open(self, window: ReactionWindow) -> None:
        if any(item.window_id == window.window_id for item in self._windows):
            raise ValueError("duplicate reaction window")
        self._windows.append(window)

    @property
    def current(self) -> ReactionWindow | None:
        return self._windows[-1] if self._windows else None

    def resolve_current(self) -> tuple[ReactionChoice, ...]:
        if not self._windows:
            return ()
        return self._windows.pop().resolve()
