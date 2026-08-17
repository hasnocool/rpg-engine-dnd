"""Utility considerations, GOAP planning, and richer deterministic actor memory."""

from __future__ import annotations

import heapq
from enum import StrEnum
from math import exp
from pydantic import BaseModel, ConfigDict, Field


class Curve(StrEnum):
    LINEAR = "linear"
    INVERSE = "inverse"
    LOGISTIC = "logistic"
    STEP = "step"


class Consideration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    weight: float = 1.0
    curve: Curve = Curve.LINEAR
    threshold: float = 0.5

    def score(self, value: float) -> float:
        normalized = max(0.0, min(1.0, value))
        if self.curve == Curve.LINEAR:
            result = normalized
        elif self.curve == Curve.INVERSE:
            result = 1.0 - normalized
        elif self.curve == Curve.LOGISTIC:
            result = 1.0 / (1.0 + exp(-10.0 * (normalized - self.threshold)))
        else:
            result = 1.0 if normalized >= self.threshold else 0.0
        return result * self.weight


class UtilityAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action_id: str
    base_score: float = 0.0
    considerations: tuple[Consideration, ...] = ()


class UtilityEvaluator:
    def score(self, action: UtilityAction, facts: dict[str, float]) -> float:
        score = action.base_score
        for consideration in action.considerations:
            score += consideration.score(float(facts.get(consideration.key, 0.0)))
        return score

    def choose(self, actions: list[UtilityAction], facts: dict[str, float]) -> UtilityAction:
        if not actions:
            raise ValueError("no utility actions")
        return max(actions, key=lambda item: (self.score(item, facts), item.action_id))


class GOAPAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action_id: str
    preconditions: dict[str, object] = Field(default_factory=dict)
    effects: dict[str, object] = Field(default_factory=dict)
    cost: float = Field(default=1.0, ge=0)


class GOAPPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    actions: tuple[str, ...]
    total_cost: float = Field(ge=0)
    final_state: dict[str, object]


class GOAPPlanner:
    """Bounded deterministic forward planner for small actor decision spaces."""

    def plan(
        self,
        initial: dict[str, object],
        goal: dict[str, object],
        actions: list[GOAPAction],
        *,
        max_expansions: int = 1024,
    ) -> GOAPPlan:
        def satisfied(state: dict[str, object], expected: dict[str, object]) -> bool:
            return all(state.get(key) == value for key, value in expected.items())

        if satisfied(initial, goal):
            return GOAPPlan(actions=(), total_cost=0, final_state=dict(initial))
        ordered = sorted(actions, key=lambda item: item.action_id)
        frontier: list[tuple[float, int, tuple[str, ...], dict[str, object]]] = [(0.0, 0, (), dict(initial))]
        seen: dict[tuple[tuple[str, str], ...], float] = {}
        expansions = 0
        while frontier:
            cost, depth, path, state = heapq.heappop(frontier)
            signature = tuple(sorted((key, repr(value)) for key, value in state.items()))
            if seen.get(signature, float("inf")) <= cost:
                continue
            seen[signature] = cost
            if satisfied(state, goal):
                return GOAPPlan(actions=path, total_cost=cost, final_state=state)
            expansions += 1
            if expansions > max_expansions:
                break
            for action in ordered:
                if not satisfied(state, action.preconditions):
                    continue
                next_state = dict(state)
                next_state.update(action.effects)
                heapq.heappush(frontier, (cost + action.cost, depth + 1, (*path, action.action_id), next_state))
        raise ValueError("no GOAP plan found within expansion budget")


class MemoryKind(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"
    LOCATION = "location"
    THREAT = "threat"


class RichMemory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    memory_id: str
    kind: MemoryKind
    subject_id: str
    fact: str
    sequence: int = Field(ge=0)
    confidence: float = Field(default=1, ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    source_ids: tuple[str, ...] = ()

    def confidence_at(self, sequence: int, *, half_life: int = 10_000) -> float:
        if half_life <= 0:
            raise ValueError("half_life must be positive")
        age = max(0, sequence - self.sequence)
        return self.confidence * (0.5 ** (age / half_life))


class MemoryStore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memories: list[RichMemory] = Field(default_factory=list)

    def remember(self, memory: RichMemory, *, max_items: int = 512) -> None:
        self.memories.append(memory)
        if len(self.memories) > max_items:
            self.memories.sort(key=lambda item: (item.importance, item.sequence, item.memory_id), reverse=True)
            self.memories = self.memories[:max_items]

    def consolidate(self, subject_id: str, *, sequence: int) -> tuple[RichMemory, ...]:
        candidates = [item for item in self.memories if item.subject_id == subject_id]
        candidates.sort(key=lambda item: (-item.confidence_at(sequence), -item.importance, item.memory_id))
        return tuple(candidates)
