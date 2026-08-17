"""v1.9 bounded executable rule graph compiler and deterministic interpreter."""

from __future__ import annotations

from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash
from .rules import DamageContext, Effect, ReactionOpportunity, RollContext, RulesRuntime


RuleOperation = Literal[
    "roll", "damage", "heal", "resource", "effect", "reaction", "condition",
    "state", "emit", "stop"
]


class RuleNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    op: RuleOperation
    args: dict[str, object] = Field(default_factory=dict)
    next_node: str | None = None
    true_node: str | None = None
    false_node: str | None = None


class RuleDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    entry_point: str
    nodes: dict[str, RuleNode]
    capabilities: frozenset[str] = frozenset()
    allowed_state_paths: frozenset[str] = frozenset()
    provenance: dict[str, str] = Field(default_factory=dict)


class CompiledRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    document: RuleDocument
    graph_hash: str
    node_budget: int
    effect_budget: int


class ExecutionTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    op: str
    result: dict[str, object] = Field(default_factory=dict)


class RuleExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    graph_hash: str
    traces: tuple[ExecutionTrace, ...]
    emitted: tuple[str, ...]
    state: dict[str, object]


class RuleCompiler:
    def __init__(self, *, max_nodes: int = 256, max_effects: int = 128) -> None:
        self.max_nodes = max_nodes
        self.max_effects = max_effects

    def compile(self, document: RuleDocument) -> CompiledRule:
        if len(document.nodes) > self.max_nodes:
            raise ValueError("rule graph exceeds node budget")
        if document.entry_point not in document.nodes:
            raise ValueError("rule graph entry point is missing")
        for node in document.nodes.values():
            for target in (node.next_node, node.true_node, node.false_node):
                if target is not None and target not in document.nodes:
                    raise ValueError(f"rule node references missing target: {target}")
            if node.op == "state":
                path = str(node.args.get("path", ""))
                if path not in document.allowed_state_paths:
                    raise ValueError(f"state path not allowlisted: {path}")
        graph_hash = canonical_hash(document.model_dump(mode="json"))
        return CompiledRule(
            document=document.model_copy(deep=True),
            graph_hash=graph_hash,
            node_budget=self.max_nodes,
            effect_budget=self.max_effects,
        )


class RuleInterpreter:
    def __init__(self, runtime: RulesRuntime, *, step_budget: int = 1024) -> None:
        self.runtime = runtime
        self.step_budget = step_budget

    @staticmethod
    def _set_path(state: dict[str, object], path: str, value: object) -> None:
        parts = path.split(".")
        cursor: dict[str, object] = state
        for part in parts[:-1]:
            child = cursor.setdefault(part, {})
            if not isinstance(child, dict):
                raise ValueError("state path crosses non-object value")
            cursor = child
        cursor[parts[-1]] = value

    def execute(self, compiled: CompiledRule, *, state: dict[str, object] | None = None) -> RuleExecutionResult:
        if canonical_hash(compiled.document.model_dump(mode="json")) != compiled.graph_hash:
            raise ValueError("compiled graph hash verification failed")
        working = deepcopy(state or {})
        traces: list[ExecutionTrace] = []
        emitted: list[str] = []
        effects = 0
        current = compiled.document.entry_point
        for _ in range(self.step_budget):
            node = compiled.document.nodes[current]
            args = node.args
            result: dict[str, object] = {}
            next_node = node.next_node
            if node.op == "roll":
                outcome = self.runtime.roll(
                    RollContext(
                        actor_id=str(args.get("actor_id", "system")),
                        purpose=str(args.get("purpose", compiled.document.rule_id)),
                        bonus=int(args.get("bonus", 0)),
                    )
                )
                result = {"total": outcome.total, "selected": outcome.selected}
                threshold = args.get("threshold")
                if threshold is not None:
                    next_node = node.true_node if outcome.total >= int(threshold) else node.false_node
            elif node.op == "damage":
                outcome = self.runtime.damage(
                    DamageContext(
                        source_id=str(args.get("source_id", "system")),
                        target_id=str(args["target_id"]),
                        expression=str(args.get("expression", "1d1")),
                        damage_type=str(args.get("damage_type", "untyped")),
                    )
                )
                result = {"amount": outcome.amount, "damage_type": outcome.damage_type}
            elif node.op == "heal":
                result = {"amount": max(0, int(args.get("amount", 0)))}
            elif node.op == "resource":
                result = {"resource": str(args["resource"]), "delta": int(args.get("delta", 0))}
            elif node.op in {"effect", "condition"}:
                effects += 1
                if effects > compiled.effect_budget:
                    raise ValueError("rule execution exceeded effect budget")
                effect = Effect(
                    effect_id=str(args.get("effect_id", f"{compiled.document.rule_id}:{current}")),
                    source_id=str(args.get("source_id", "system")),
                    target_id=str(args["target_id"]),
                    kind=str(args.get("kind", node.op)),
                    payload=dict(args.get("payload", {})),
                )
                generated = self.runtime.apply_effect(effect)
                result = {"effects": [item.effect_id for item in generated]}
            elif node.op == "reaction":
                opportunity = ReactionOpportunity(
                    reaction_id=str(args["reaction_id"]),
                    actor_id=str(args["actor_id"]),
                    trigger=str(args.get("trigger", compiled.document.rule_id)),
                )
                self.runtime.offer_reaction(opportunity)
                result = {"reaction_id": opportunity.reaction_id}
            elif node.op == "state":
                path = str(args["path"])
                if path not in compiled.document.allowed_state_paths:
                    raise ValueError("state mutation path is not allowlisted")
                self._set_path(working, path, deepcopy(args.get("value")))
                result = {"path": path}
            elif node.op == "emit":
                emitted.append(str(args["event"]))
                result = {"event": emitted[-1]}
            elif node.op == "stop":
                traces.append(ExecutionTrace(node_id=current, op=node.op, result=result))
                break
            traces.append(ExecutionTrace(node_id=current, op=node.op, result=result))
            if next_node is None:
                break
            current = next_node
        else:
            raise ValueError("rule execution exceeded step budget")
        return RuleExecutionResult(
            graph_hash=compiled.graph_hash,
            traces=tuple(traces),
            emitted=tuple(emitted),
            state=working,
        )
