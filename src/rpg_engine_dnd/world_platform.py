"""Integrated authoritative platform engine spanning core commands and compiled rules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .commands import Command
from .compiler import RuleCompiler, RuleDocument, RuleExecutionResult, RuleInterpreter
from .engine import SimulationEngine
from .events import Event
from .knowledge import KnowledgeAuthority
from .models import World
from .orchestrator import CampaignOrchestrator
from .rules import RulesRuntime


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
    """Single authority boundary shared by clients, hosting, replay, and rules execution."""

    def __init__(self, *, seed: int | str | bytes) -> None:
        self.core = SimulationEngine(seed=seed)
        self.rules = RulesRuntime(seed=f"{seed!s}:rules")
        self.compiler = RuleCompiler()
        self.orchestrator = CampaignOrchestrator()
        self.knowledge = KnowledgeAuthority()
        self.rule_state: dict[str, object] = {}

    @property
    def world(self) -> World:
        return self.core.world

    def handle(self, command: Command | RuleExecuteCommand) -> Event:
        if isinstance(command, RuleExecuteCommand):
            return self.execute_rule(command)[0]
        return self.core.handle(command)

    def execute_rule(self, command: RuleExecuteCommand) -> tuple[Event, RuleExecutionResult]:
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

    def snapshot(self) -> dict[str, Any]:
        return {
            "world": self.core.world.model_dump(mode="json"),
            "rule_state": deepcopy(self.rule_state),
            "orchestrator": self.orchestrator.model_dump(mode="json"),
        }
