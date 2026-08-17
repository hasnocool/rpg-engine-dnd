"""Authoritative v0.1 simulation engine."""

from __future__ import annotations

from copy import deepcopy
from typing import NoReturn

from .commands import (
    Command,
    CreateEntity,
    DeleteEntity,
    PatchComponent,
    RemoveComponent,
    SetComponent,
)
from .dice import DiceStreams
from .events import Event
from .models import Entity, World


class SimulationEngine:
    """Apply validated commands to authoritative world state.

    State changes only happen here. A failed command does not increment the revision.
    """

    def __init__(self, *, seed: int | str | bytes, world: World | None = None) -> None:
        self.world = world.clone() if world is not None else World()
        self.dice = DiceStreams(seed)

    def handle(self, command: Command) -> Event:
        if isinstance(command, CreateEntity):
            return self._create(command)
        if isinstance(command, DeleteEntity):
            return self._delete(command)
        if isinstance(command, SetComponent):
            return self._set_component(command)
        if isinstance(command, PatchComponent):
            return self._patch_component(command)
        if isinstance(command, RemoveComponent):
            return self._remove_component(command)
        self._unsupported(command)

    def _next_event(
        self,
        command: Command,
        *,
        kind: str,
        entity_id: str | None,
        payload: dict[str, object] | None = None,
    ) -> Event:
        self.world.revision += 1
        return Event(
            sequence=self.world.revision,
            command_id=command.command_id,
            kind=kind,
            entity_id=entity_id,
            payload={} if payload is None else payload,
        )

    def _create(self, command: CreateEntity) -> Event:
        if command.entity_id in self.world.entities:
            raise ValueError(f"entity already exists: {command.entity_id}")
        entity = Entity(
            entity_id=command.entity_id,
            components=deepcopy(command.components),
        )
        self.world.entities[command.entity_id] = entity
        payload: dict[str, object] = {"components": deepcopy(command.components)}
        return self._next_event(
            command,
            kind="entity.created",
            entity_id=command.entity_id,
            payload=payload,
        )

    def _delete(self, command: DeleteEntity) -> Event:
        entity = self.world.entity(command.entity_id)
        payload = {"components": deepcopy(entity.components)}
        del self.world.entities[command.entity_id]
        return self._next_event(
            command,
            kind="entity.deleted",
            entity_id=command.entity_id,
            payload=payload,
        )

    def _set_component(self, command: SetComponent) -> Event:
        entity = self.world.entity(command.entity_id)
        entity.components[command.component] = deepcopy(command.value)
        return self._next_event(
            command,
            kind="component.set",
            entity_id=command.entity_id,
            payload={"component": command.component, "value": deepcopy(command.value)},
        )

    def _patch_component(self, command: PatchComponent) -> Event:
        entity = self.world.entity(command.entity_id)
        if command.component not in entity.components:
            raise KeyError(
                f"unknown component {command.component!r} on entity {command.entity_id!r}"
            )
        entity.components[command.component].update(deepcopy(command.patch))
        return self._next_event(
            command,
            kind="component.patched",
            entity_id=command.entity_id,
            payload={"component": command.component, "patch": deepcopy(command.patch)},
        )

    def _remove_component(self, command: RemoveComponent) -> Event:
        entity = self.world.entity(command.entity_id)
        try:
            value = entity.components.pop(command.component)
        except KeyError as exc:
            raise KeyError(
                f"unknown component {command.component!r} on entity {command.entity_id!r}"
            ) from exc
        return self._next_event(
            command,
            kind="component.removed",
            entity_id=command.entity_id,
            payload={"component": command.component, "value": deepcopy(value)},
        )

    @staticmethod
    def _unsupported(command: object) -> NoReturn:
        raise TypeError(f"unsupported command type: {type(command).__name__}")
