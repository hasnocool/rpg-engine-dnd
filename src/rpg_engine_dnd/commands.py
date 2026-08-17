"""Typed commands accepted by the authoritative simulation engine."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _CommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command_id: str = Field(min_length=1)


class CreateEntity(_CommandBase):
    kind: Literal["entity.create"] = "entity.create"
    entity_id: str = Field(min_length=1)
    components: dict[str, dict[str, Any]] = Field(default_factory=dict)


class DeleteEntity(_CommandBase):
    kind: Literal["entity.delete"] = "entity.delete"
    entity_id: str = Field(min_length=1)


class SetComponent(_CommandBase):
    kind: Literal["component.set"] = "component.set"
    entity_id: str = Field(min_length=1)
    component: str = Field(min_length=1)
    value: dict[str, Any]


class PatchComponent(_CommandBase):
    kind: Literal["component.patch"] = "component.patch"
    entity_id: str = Field(min_length=1)
    component: str = Field(min_length=1)
    patch: dict[str, Any]


class RemoveComponent(_CommandBase):
    kind: Literal["component.remove"] = "component.remove"
    entity_id: str = Field(min_length=1)
    component: str = Field(min_length=1)


Command = CreateEntity | DeleteEntity | SetComponent | PatchComponent | RemoveComponent
