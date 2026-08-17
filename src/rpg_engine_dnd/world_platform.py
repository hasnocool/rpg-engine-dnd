"""Integrated authoritative platform engine spanning core commands and compiled rules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from .commands import Command
from .compiler import RuleCompiler, RuleDocument, RuleExecutionResult, RuleInterpreter
from .engine import SimulationEngine
from .events import Event
from .knowledge import KnowledgeAuthority
from .models import World
from .orchestrator import CampaignOrchestrator
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

    def handle(self, command: Command | RuleExecuteCommand) -> Event:
        before = self._authoritative_state()
        before_rule_state = deepcopy(self.rule_state)
        try:
            event = self.runtime.execute(cast(CommandLike, command))
        except Exception:
            self.rule_state = before_rule_state
            raise
        after = self._authoritative_state()
        self.semantic_journal.append(
            command_id=command.command_id,
            event_kind=event.kind,
            before=before,
            after=after,
            entity_id=event.entity_id,
            data=deepcopy(event.payload),
        )
        return event

    def execute_rule(self, command: RuleExecuteCommand) -> tuple[Event, RuleExecutionResult]:
        event = self.handle(command)
        try:
            result = self._rule_results.pop(command.command_id)
        except KeyError as exc:
            raise RuntimeError("rule command completed without an execution result") from exc
        return event, result

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
