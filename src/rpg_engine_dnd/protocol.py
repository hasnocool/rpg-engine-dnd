"""Shared client protocol, optimistic concurrency, and interest-managed projections."""

from __future__ import annotations

from enum import IntEnum
from math import dist
from pydantic import BaseModel, ConfigDict, Field


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    protocol_version: str = "1"
    capabilities: frozenset[str] = frozenset()


class AssetBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: str
    asset_id: str
    variant: str | None = None


class CommandEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    command_id: str
    kind: str
    expected_world_revision: int | None = Field(default=None, ge=0)
    actor_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    command_id: str
    accepted: bool
    world_revision: int = Field(ge=0)
    event_sequence: int | None = Field(default=None, ge=1)
    rejection: str | None = None


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(ge=1)
    kind: str
    entity_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class RuntimeSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    revision: int = Field(ge=0)
    entities: dict[str, dict[str, object]] = Field(default_factory=dict)
    capabilities: CapabilityManifest = Field(default_factory=CapabilityManifest)


class RuntimeDelta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    base_revision: int = Field(ge=0)
    target_revision: int = Field(ge=0)
    operations: tuple[dict[str, object], ...] = ()


def validate_expected_revision(envelope: CommandEnvelope, actual_revision: int) -> None:
    expected = envelope.expected_world_revision
    if expected is not None and expected != actual_revision:
        raise ValueError(f"stale world revision: expected {expected}, actual {actual_revision}")


class PriorityTier(IntEnum):
    BACKGROUND = 0
    NORMAL = 1
    IMPORTANT = 2
    CRITICAL = 3


class AreaOfInterest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    center: tuple[float, ...]
    radius: float = Field(gt=0)
    explicit_entity_ids: frozenset[str] = frozenset()
    tag_filters: frozenset[str] = frozenset()


class InterestEntity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: str
    position: tuple[float, ...] | None = None
    tags: frozenset[str] = frozenset()
    priority: PriorityTier = PriorityTier.NORMAL
    lod: int = Field(default=0, ge=0)


class InterestManager:
    def select(self, area: AreaOfInterest, entities: list[InterestEntity]) -> tuple[InterestEntity, ...]:
        selected: list[InterestEntity] = []
        for entity in entities:
            explicit = entity.entity_id in area.explicit_entity_ids
            tag_match = bool(area.tag_filters.intersection(entity.tags))
            nearby = (
                entity.position is not None
                and len(entity.position) == len(area.center)
                and dist(entity.position, area.center) <= area.radius
            )
            if explicit or tag_match or nearby or entity.priority == PriorityTier.CRITICAL:
                selected.append(entity)
        return tuple(sorted(selected, key=lambda item: (-int(item.priority), item.lod, item.entity_id)))
