"""v0.7 AI game-master boundaries and deterministic procedural content helpers."""

from __future__ import annotations

from collections import deque
from pydantic import BaseModel, ConfigDict, Field

from .dice import DiceStreams
from .events import Event


class NPCPersonality(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    npc_id: str
    traits: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    voice_tags: tuple[str, ...] = ()


class EncounterSeed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    encounter_id: str
    creature_ids: tuple[str, ...]
    difficulty_score: int = Field(ge=0)
    reason: str


class GeneratedQuest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    quest_id: str
    objective_event: str
    target_count: int = Field(ge=1)
    hook: str


class BoundedMemory:
    def __init__(self, max_items: int = 64) -> None:
        if max_items < 1:
            raise ValueError("max_items must be positive")
        self._items: deque[str] = deque(maxlen=max_items)

    def add(self, memory: str) -> None:
        self._items.append(memory)

    def context(self) -> tuple[str, ...]:
        return tuple(self._items)


class AuthoritativeEventNarrator:
    """Narration sees only emitted events, never mutable authoritative state."""

    def narrate(self, event: Event) -> str:
        subject = "the world" if event.entity_id is None else event.entity_id
        return f"{subject}: {event.kind}"


class ProceduralDirector:
    def __init__(self, seed: int | str | bytes) -> None:
        self.dice = DiceStreams(seed)

    def encounter(self, *, index: int, creature_pool: tuple[str, ...], budget: int) -> EncounterSeed:
        if not creature_pool:
            raise ValueError("creature_pool must not be empty")
        if budget < 1:
            raise ValueError("budget must be positive")
        rng = self.dice.stream("encounter-generator")
        count = max(1, min(len(creature_pool), rng.randint(1, min(4, budget))))
        ordered = list(creature_pool)
        rng.shuffle(ordered)
        chosen = tuple(sorted(ordered[:count]))
        return EncounterSeed(
            encounter_id=f"generated-encounter-{index}",
            creature_ids=chosen,
            difficulty_score=count,
            reason="deterministic procedural encounter",
        )

    def quest(self, *, index: int, event_pool: tuple[str, ...]) -> GeneratedQuest:
        if not event_pool:
            raise ValueError("event_pool must not be empty")
        rng = self.dice.stream("quest-generator")
        event = event_pool[rng.randrange(len(event_pool))]
        target = rng.randint(1, 4)
        return GeneratedQuest(
            quest_id=f"generated-quest-{index}",
            objective_event=event,
            target_count=target,
            hook=f"Respond to {event}",
        )
