"""Core entity/component and world-state models."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ComponentValue = dict[str, Any]


class AbilityScores(BaseModel):
    """Ruleset-neutral six-ability score component."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    strength: int = Field(default=10, ge=1)
    dexterity: int = Field(default=10, ge=1)
    constitution: int = Field(default=10, ge=1)
    intelligence: int = Field(default=10, ge=1)
    wisdom: int = Field(default=10, ge=1)
    charisma: int = Field(default=10, ge=1)


class Entity(BaseModel):
    """An entity is an identifier plus an open set of serializable components."""

    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(min_length=1)
    components: dict[str, ComponentValue] = Field(default_factory=dict)

    def clone(self) -> "Entity":
        return Entity.model_validate(self.model_dump(mode="python"))


class World(BaseModel):
    """Authoritative simulation state."""

    model_config = ConfigDict(extra="forbid")
    revision: int = Field(default=0, ge=0)
    entities: dict[str, Entity] = Field(default_factory=dict)

    def clone(self) -> "World":
        return World.model_validate(deepcopy(self.model_dump(mode="python")))

    def entity(self, entity_id: str) -> Entity:
        try:
            return self.entities[entity_id]
        except KeyError as exc:
            raise KeyError(f"unknown entity: {entity_id}") from exc

    def canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
