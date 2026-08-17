"""Integrated authoritative platform engine spanning core commands and compiled rules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash
from .commands import Command
from .compiler import RuleCompiler, RuleDocument, RuleExecutionResult, RuleInterpreter
from .engine import SimulationEngine
from .events import Event
from .knowledge import KnowledgeAuthority
from .models import World
from .orchestrator import CampaignOrchestrator, Scene, SceneStatus
from .rules import RulesRuntime
from .runtime import AuthoritativeRuntime, CommandBus, CommandLike
from .scheduler import SimulationScheduler
from .semantic_events import SemanticEventJournal


class RuleExecuteCommand(BaseModel):
    """Authoritative command for bounded executable-rule graphs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = "rule.execute"
    command_id: str = Field(min_length=1)
    document: RuleDocument
    state: dict[str, object] = Field(default_factory=dict)
    entity_id: str | None = None
    component: str | None = None


class WorldPlatformEngine:
    """Single atomic authority boundary shared by clients, hosting, replay, and rules execution."""

    _CORE_KINDS = (
        "entity.create",
        "entity.delete",
        "component.set",
        "component.patch",
        "component.remove",
    )

    def __init__(self, *, seed: int | str | bytes) -> None:
        self.core = SimulationEngine(seed=seed)
        self.rules = RulesRuntime(seed=f"{seed!s}:rules")
        self.compiler = RuleCompiler()
        self.orchestrator = CampaignOrchestrator()
        self.knowledge = KnowledgeAuthority()
        self.scheduler = SimulationScheduler()
        self.rule_state: dict[str, object] = {}
        self._rule_results: dict[str, RuleExecutionResult] = {}
        self._completed_events: dict[str, Event] = {}
        self._command_hashes: dict[str, str] = {}
        self._scene_command_sequence = 0

        self.command_bus = CommandBus()
        for kind in self._CORE_KINDS:
            self.command_bus.register(kind, self._handle_core_command)
        self.command_bus.register("rule.execute", self._handle_rule_command)
        self.runtime = AuthoritativeRuntime(self.core.world, self.command_bus)
        self.semantic_journal = SemanticEventJournal(self._authoritative_state())

    @property
    def world(self) -> World:
        return self.core.world

    def _handle_core_command(self, command: CommandLike) -> Event:
        return self.core.handle(cast(Command, command))

    def _handle_rule_command(self, command: CommandLike) -> Event:
        typed = cast(RuleExecuteCommand, command)
        event, result = self._execute_rule_impl(typed)
        self._rule_results[typed.command_id] = result
        return event

    @staticmethod
    def _command_hash(command: Command | RuleExecuteCommand) -> str:
        return canonical_hash(command.model_dump(mode="json"))

    def _completed_event(self, command: Command | RuleExecuteCommand) -> Event | None:
        existing = self._completed_events.get(command.command_id)
        if existing is None:
            return None
        command_hash = self._command_hash(command)
        if self._command_hashes[command.command_id] != command_hash:
            raise ValueError("command_id was reused for a different command")
        return existing.model_copy(deep=True)

    def handle(self, command: Command | RuleExecuteCommand) -> Event:
        completed = self._completed_event(command)
        if completed is not None:
            return completed

        before = self._authoritative_state()
        before_world = self.core.world.clone()
        before_rule_state = deepcopy(self.rule_state)
        try:
            event = self.runtime.execute(cast(CommandLike, command))
            after = self._authoritative_state()
            self.semantic_journal.append(
                command_id=command.command_id,
                event_kind=event.kind,
                before=before,
                after=after,
                entity_id=event.entity_id,
                data=deepcopy(event.payload),
            )
        except Exception:
            self.core.world.revision = before_world.revision
            self.core.world.entities = {
                entity_id: entity.clone() for entity_id, entity in before_world.entities.items()
            }
            self.rule_state = before_rule_state
            self._rule_results.pop(command.command_id, None)
            raise

        self._completed_events[command.command_id] = event.model_copy(deep=True)
        self._command_hashes[command.command_id] = self._command_hash(command)
        return event

    def execute_rule(self, command: RuleExecuteCommand) -> tuple[Event, RuleExecutionResult]:
        event = self.handle(command)
        try:
            result = self._rule_results[command.command_id]
        except KeyError as exc:
            raise RuntimeError("rule command completed without an execution result") from exc
        return event, result.model_copy(deep=True)

    def _execute_rule_impl(self, command: RuleExecuteCommand) -> tuple[Event, RuleExecutionResult]:
        compiled = self.compiler.compile(command.document)
        result = RuleInterpreter(self.rules).execute(compiled, state=deepcopy(command.state))
        self.rule_state[command.document.rule_id] = deepcopy(result.state)

        if command.entity_id is not None:
            entity = self.core.world.entity(command.entity_id)
            component_name = command.component or "rules"
            entity.components[component_name] = deepcopy(result.state)

        self.core.world.revision += 1
        event = Event(
            sequence=self.core.world.revision,
            command_id=command.command_id,
            kind="rule.executed",
            entity_id=command.entity_id,
            payload={
                "rule_id": command.document.rule_id,
                "graph_hash": result.graph_hash,
                "emitted": list(result.emitted),
                "state": deepcopy(result.state),
            },
        )
        return event, result

    def _next_scene_command_id(self, operation: str, scene_id: str) -> str:
        self._scene_command_sequence += 1
        return f"scene:{operation}:{scene_id}:{self._scene_command_sequence}"

    def register_scene(self, scene: Scene) -> Scene:
        before = self._authoritative_state()
        previous = self.orchestrator.model_copy(deep=True)
        try:
            self.orchestrator.register(scene.model_copy(deep=True))
            after = self._authoritative_state()
            self.semantic_journal.append(
                command_id=self._next_scene_command_id("register", scene.scene_id),
                event_kind="scene.registered",
                before=before,
                after=after,
                data={"scene_id": scene.scene_id},
            )
        except Exception:
            self.orchestrator = previous
            raise
        return self.orchestrator.scenes[scene.scene_id].model_copy(deep=True)

    def transition_scene(self, scene_id: str, status: SceneStatus) -> Scene:
        before = self._authoritative_state()
        previous = self.orchestrator.model_copy(deep=True)
        try:
            scene = self.orchestrator.transition(scene_id, status)
            after = self._authoritative_state()
            self.semantic_journal.append(
                command_id=self._next_scene_command_id(f"transition:{status.value}", scene_id),
                event_kind="scene.transitioned",
                before=before,
                after=after,
                data={"scene_id": scene_id, "status": status.value},
            )
        except Exception:
            self.orchestrator = previous
            raise
        return scene.model_copy(deep=True)

    def _authoritative_state(self) -> dict[str, object]:
        return {
            "world": self.core.world.model_dump(mode="json"),
            "rule_state": deepcopy(self.rule_state),
            "orchestrator": self.orchestrator.model_dump(mode="json"),
            "scheduler": {
                "tick": self.scheduler.tick,
                "pending": [
                    {
                        "task_id": task.task_id,
                        "due_tick": task.due_tick,
                        "domain": task.domain.value,
                        "kind": task.kind,
                        "actor_id": task.actor_id,
                        "payload": deepcopy(task.payload),
                    }
                    for task in self.scheduler.pending()
                ],
            },
        }

    def snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = self._authoritative_state()
        snapshot["journal_head_hash"] = self.semantic_journal.journal.head_hash
        return snapshot
