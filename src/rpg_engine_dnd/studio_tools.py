"""Creator Studio rule debugging, state diffs, reference inspection, and simulation previews."""

from __future__ import annotations

from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field


class DebugStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    index: int = Field(ge=0)
    node_id: str
    operation: str
    inputs: dict[str, object] = Field(default_factory=dict)
    outputs: dict[str, object] = Field(default_factory=dict)
    state_diff: dict[str, object] = Field(default_factory=dict)
    breakpoint_hit: bool = False


class RuleDebugSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_id: str
    breakpoints: set[str] = Field(default_factory=set)
    watch_paths: set[str] = Field(default_factory=set)
    steps: list[DebugStep] = Field(default_factory=list)
    cursor: int = 0

    def ingest_trace(self, trace: list[dict[str, object]]) -> None:
        self.steps = []
        previous_state: dict[str, object] = {}
        for index, raw in enumerate(trace):
            node_id = str(raw.get("node_id", index))
            state = raw.get("state")
            current_state = dict(state) if isinstance(state, dict) else previous_state
            diff = self._diff(previous_state, current_state)
            self.steps.append(
                DebugStep(
                    index=index,
                    node_id=node_id,
                    operation=str(raw.get("operation", raw.get("op", "unknown"))),
                    inputs=dict(raw.get("inputs", {})) if isinstance(raw.get("inputs"), dict) else {},
                    outputs=dict(raw.get("outputs", {})) if isinstance(raw.get("outputs"), dict) else {},
                    state_diff=diff,
                    breakpoint_hit=node_id in self.breakpoints,
                )
            )
            previous_state = deepcopy(current_state)
        self.cursor = 0

    def step(self) -> DebugStep | None:
        if self.cursor >= len(self.steps):
            return None
        result = self.steps[self.cursor]
        self.cursor += 1
        return result

    def continue_until_breakpoint(self) -> tuple[DebugStep, ...]:
        emitted: list[DebugStep] = []
        while (step := self.step()) is not None:
            emitted.append(step)
            if step.breakpoint_hit:
                break
        return tuple(emitted)

    @staticmethod
    def _diff(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                result[key] = {"before": deepcopy(before.get(key)), "after": deepcopy(after.get(key))}
        return result


class ContentReferenceGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edges: dict[str, set[str]] = Field(default_factory=dict)

    def link(self, source: str, target: str) -> None:
        self.edges.setdefault(source, set()).add(target)

    def dependencies(self, source: str) -> tuple[str, ...]:
        return tuple(sorted(self.edges.get(source, set())))

    def dependents(self, target: str) -> tuple[str, ...]:
        return tuple(sorted(source for source, targets in self.edges.items() if target in targets))


class SimulationPreview(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    scenario_id: str
    sample_count: int = Field(ge=1)
    metrics: dict[str, float] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
