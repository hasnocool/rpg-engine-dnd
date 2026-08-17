"""Typed deterministic rule IR validation and safe optimization passes."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class ValueType(StrEnum):
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"
    OBJECT = "object"
    ANY = "any"


class IROp(StrEnum):
    CONST = "const"
    READ = "read"
    WRITE = "write"
    ROLL = "roll"
    ADD = "add"
    MULTIPLY = "multiply"
    COMPARE = "compare"
    BRANCH = "branch"
    EFFECT = "effect"
    EMIT = "emit"
    STOP = "stop"


class IRInstruction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instruction_id: str
    op: IROp
    output_type: ValueType = ValueType.ANY
    args: dict[str, object] = Field(default_factory=dict)
    next_ids: tuple[str, ...] = ()
    capability: str | None = None
    gas: int = Field(default=1, ge=0)


class CompiledPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entry_id: str
    instructions: tuple[IRInstruction, ...]
    required_capabilities: frozenset[str]
    gas_estimate: int = Field(ge=0)


class RuleIRCompiler:
    """Static validation/optimization layer before the existing bounded interpreter."""

    def compile(self, entry_id: str, instructions: list[IRInstruction], *, gas_limit: int = 10_000) -> CompiledPlan:
        index = {item.instruction_id: item for item in instructions}
        if len(index) != len(instructions):
            raise ValueError("duplicate IR instruction id")
        if entry_id not in index:
            raise ValueError("IR entry does not exist")
        for instruction in instructions:
            for target in instruction.next_ids:
                if target not in index:
                    raise ValueError(f"unknown IR target: {target}")
            if instruction.op in {IROp.READ, IROp.WRITE} and not isinstance(instruction.args.get("path"), str):
                raise ValueError(f"{instruction.op} requires a string path")
        reachable: set[str] = set()
        pending = [entry_id]
        while pending:
            current = pending.pop()
            if current in reachable:
                continue
            reachable.add(current)
            pending.extend(reversed(index[current].next_ids))
        optimized = tuple(item for item in instructions if item.instruction_id in reachable)
        gas = sum(item.gas for item in optimized)
        if gas > gas_limit:
            raise ValueError(f"rule gas estimate exceeds limit: {gas} > {gas_limit}")
        capabilities = frozenset(item.capability for item in optimized if item.capability is not None)
        return CompiledPlan(
            entry_id=entry_id,
            instructions=optimized,
            required_capabilities=capabilities,
            gas_estimate=gas,
        )
