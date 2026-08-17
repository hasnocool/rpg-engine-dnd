"""v1.5 perception, goals, utility AI, behavior trees, planning, schedules, and memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class PerceivedEntity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: str
    distance: float = Field(ge=0)
    tags: frozenset[str] = frozenset()
    public_state: dict[str, object] = Field(default_factory=dict)


class PerceptionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    actor_id: str
    sequence: int = Field(ge=0)
    entities: tuple[PerceivedEntity, ...] = ()
    facts: dict[str, object] = Field(default_factory=dict)


class ActorGoal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal_id: str
    priority: float = 1.0
    target_id: str | None = None
    tags: set[str] = Field(default_factory=set)


class ActorMemory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(ge=0)
    subject_id: str
    fact: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class UtilityOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    action: str
    base_score: float = 0.0
    requires_tags: frozenset[str] = frozenset()
    goal_tags: frozenset[str] = frozenset()


class UtilityAI:
    def score(self, option: UtilityOption, snapshot: PerceptionSnapshot, goals: list[ActorGoal]) -> float:
        visible_tags = set().union(*(entity.tags for entity in snapshot.entities)) if snapshot.entities else set()
        if not option.requires_tags.issubset(visible_tags):
            return float("-inf")
        matching_priority = sum(
            goal.priority for goal in goals if option.goal_tags.intersection(goal.tags)
        )
        return option.base_score + matching_priority

    def choose(self, options: list[UtilityOption], snapshot: PerceptionSnapshot, goals: list[ActorGoal]) -> UtilityOption:
        if not options:
            raise ValueError("no utility options")
        return max(options, key=lambda item: (self.score(item, snapshot, goals), item.action))


class BTStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"


class BehaviorNode:
    def tick(self, facts: dict[str, object]) -> BTStatus:
        raise NotImplementedError


@dataclass(slots=True)
class ConditionNode(BehaviorNode):
    key: str
    expected: object

    def tick(self, facts: dict[str, object]) -> BTStatus:
        return BTStatus.SUCCESS if facts.get(self.key) == self.expected else BTStatus.FAILURE


@dataclass(slots=True)
class ActionNode(BehaviorNode):
    action: str

    def tick(self, facts: dict[str, object]) -> BTStatus:
        facts["selected_action"] = self.action
        return BTStatus.SUCCESS


@dataclass(slots=True)
class SequenceNode(BehaviorNode):
    children: tuple[BehaviorNode, ...]

    def tick(self, facts: dict[str, object]) -> BTStatus:
        for child in self.children:
            status = child.tick(facts)
            if status != BTStatus.SUCCESS:
                return status
        return BTStatus.SUCCESS


@dataclass(slots=True)
class SelectorNode(BehaviorNode):
    children: tuple[BehaviorNode, ...]

    def tick(self, facts: dict[str, object]) -> BTStatus:
        for child in self.children:
            status = child.tick(facts)
            if status == BTStatus.SUCCESS:
                return status
        return BTStatus.FAILURE


class PlannedCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: str
    actor_id: str
    payload: dict[str, object] = Field(default_factory=dict)


class TacticalPlanner:
    """Produces validated command-shaped proposals; it never mutates authoritative state."""

    def plan(self, actor_id: str, snapshot: PerceptionSnapshot, action: str) -> PlannedCommand:
        if snapshot.actor_id != actor_id:
            raise ValueError("snapshot does not belong to actor")
        if action == "approach" and snapshot.entities:
            target = min(snapshot.entities, key=lambda entity: (entity.distance, entity.entity_id))
            return PlannedCommand(kind="actor.approach", actor_id=actor_id, payload={"target_id": target.entity_id})
        return PlannedCommand(kind=f"actor.{action}", actor_id=actor_id)


class LivingActor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str
    goals: list[ActorGoal] = Field(default_factory=list)
    memories: list[ActorMemory] = Field(default_factory=list)
    schedule_intents: dict[int, str] = Field(default_factory=dict)

    def remember(self, memory: ActorMemory, *, max_items: int = 128) -> None:
        self.memories.append(memory)
        if len(self.memories) > max_items:
            self.memories = self.memories[-max_items:]

    def scheduled_intent(self, minute_of_day: int) -> str | None:
        candidates = [minute for minute in self.schedule_intents if minute <= minute_of_day]
        return self.schedule_intents[max(candidates)] if candidates else None
