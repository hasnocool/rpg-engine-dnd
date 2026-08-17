"""Unified authoritative command bus, transactions, typed components, and migrations."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from .events import Event
from .models import World


class CommandLike(Protocol):
    command_id: str
    kind: str


CommandT = TypeVar("CommandT", bound=CommandLike)
CommandHandler = Callable[[CommandLike], Event]
Validator = Callable[[CommandLike, World], None]
Authorizer = Callable[[CommandLike, World], None]


@dataclass(slots=True)
class MutationSet:
    """A deterministic collection of component-level mutations."""

    touched_entities: set[str] = field(default_factory=set)
    touched_components: set[tuple[str, str]] = field(default_factory=set)

    def touch_entity(self, entity_id: str) -> None:
        self.touched_entities.add(entity_id)

    def touch_component(self, entity_id: str, component: str) -> None:
        self.touched_entities.add(entity_id)
        self.touched_components.add((entity_id, component))


@dataclass(frozen=True, slots=True)
class EventBatch:
    events: tuple[Event, ...]

    @property
    def last(self) -> Event | None:
        return self.events[-1] if self.events else None


class WorldTransaction:
    """Atomic in-memory transaction over a ``World`` clone.

    The transaction never mutates the live world until ``commit``. This makes complex
    command handlers all-or-nothing without introducing blocking I/O into the runtime.
    """

    def __init__(self, world: World) -> None:
        self._live = world
        self.world = world.clone()
        self.mutations = MutationSet()
        self._committed = False

    def commit(self) -> World:
        if self._committed:
            raise RuntimeError("transaction already committed")
        self._live.revision = self.world.revision
        self._live.entities = {
            entity_id: entity.clone() for entity_id, entity in self.world.entities.items()
        }
        self._committed = True
        return self._live

    def rollback(self) -> None:
        self._committed = False


class CommandBus:
    """Extensible command dispatcher with validation and authorization pipelines."""

    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self._validators: list[Validator] = []
        self._authorizers: list[Authorizer] = []

    def register(self, kind: str, handler: CommandHandler, *, replace: bool = False) -> None:
        if kind in self._handlers and not replace:
            raise ValueError(f"command handler already registered: {kind}")
        self._handlers[kind] = handler

    def add_validator(self, validator: Validator) -> None:
        self._validators.append(validator)

    def add_authorizer(self, authorizer: Authorizer) -> None:
        self._authorizers.append(authorizer)

    def dispatch(self, command: CommandLike, world: World) -> Event:
        for validator in self._validators:
            validator(command, world)
        for authorizer in self._authorizers:
            authorizer(command, world)
        try:
            handler = self._handlers[command.kind]
        except KeyError as exc:
            raise TypeError(f"unsupported command kind: {command.kind}") from exc
        return handler(command)


class ComponentSchema(BaseModel):
    """Registered typed component metadata while persisted state stays JSON-shaped."""

    name: str
    model_name: str
    version: int = 1


Migration = Callable[[dict[str, Any]], dict[str, Any]]


class ComponentSchemaRegistry:
    def __init__(self) -> None:
        self._models: dict[str, type[BaseModel]] = {}
        self._versions: dict[str, int] = {}
        self._migrations: dict[tuple[str, int], Migration] = {}

    def register(self, name: str, model: type[BaseModel], *, version: int = 1) -> None:
        if version < 1:
            raise ValueError("component schema version must be >= 1")
        self._models[name] = model
        self._versions[name] = version

    def register_migration(self, name: str, from_version: int, migration: Migration) -> None:
        if from_version < 1:
            raise ValueError("from_version must be >= 1")
        key = (name, from_version)
        if key in self._migrations:
            raise ValueError(f"migration already registered: {name} v{from_version}")
        self._migrations[key] = migration

    def validate(self, name: str, value: dict[str, Any]) -> dict[str, Any]:
        model = self._models[name]
        return model.model_validate(value).model_dump(mode="json")

    def migrate(self, name: str, value: dict[str, Any], *, from_version: int) -> dict[str, Any]:
        current = from_version
        target = self._versions[name]
        migrated = deepcopy(value)
        if current > target:
            raise ValueError(f"component {name!r} is newer than this runtime")
        while current < target:
            try:
                migration = self._migrations[(name, current)]
            except KeyError as exc:
                raise ValueError(f"missing migration for {name} v{current} -> v{current + 1}") from exc
            migrated = migration(migrated)
            current += 1
        return self.validate(name, migrated)


class AuthoritativeRuntime:
    """Single transaction boundary around an extensible command bus."""

    def __init__(self, world: World, bus: CommandBus) -> None:
        self.world = world
        self.bus = bus

    def execute(self, command: CommandLike) -> Event:
        """Execute atomically, restoring the exact pre-command state on failure."""
        before = self.world.clone()
        try:
            return self.bus.dispatch(command, self.world)
        except Exception:
            self.world.revision = before.revision
            self.world.entities = {
                entity_id: entity.clone() for entity_id, entity in before.entities.items()
            }
            raise
