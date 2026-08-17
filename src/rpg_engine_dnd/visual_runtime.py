"""v2.4 deterministic visual snapshots, redaction, hash-verified deltas, and replay."""

from __future__ import annotations

from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash
from .knowledge import KnowledgeView
from .models import World
from .visual import SceneAssetBinding


class VisualSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(ge=0)
    entities: dict[str, dict[str, object]]
    bindings: dict[str, SceneAssetBinding] = Field(default_factory=dict)
    snapshot_hash: str

    @classmethod
    def from_world(cls, world: World, bindings: dict[str, SceneAssetBinding] | None = None) -> "VisualSnapshot":
        entities = {
            entity_id: entity.model_dump(mode="json")
            for entity_id, entity in sorted(world.entities.items())
        }
        binding_map = dict(bindings or {})
        material = {"sequence": world.revision, "entities": entities, "bindings": {k: v.model_dump(mode="json") for k, v in sorted(binding_map.items())}}
        return cls(sequence=world.revision, entities=entities, bindings=binding_map, snapshot_hash=canonical_hash(material))

    @classmethod
    def from_knowledge(cls, view: KnowledgeView, bindings: dict[str, SceneAssetBinding] | None = None) -> "VisualSnapshot":
        entities = {
            entity_id: {"entity_id": entity_id, "components": deepcopy(components)}
            for entity_id, components in sorted(view.entities.items())
        }
        binding_map = {key: value for key, value in (bindings or {}).items() if key in entities}
        material = {"sequence": view.sequence, "entities": entities, "bindings": {k: v.model_dump(mode="json") for k, v in sorted(binding_map.items())}}
        return cls(sequence=view.sequence, entities=entities, bindings=binding_map, snapshot_hash=canonical_hash(material))


class DeltaOperation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    op: Literal["add", "replace", "remove"]
    entity_id: str
    value: dict[str, object] | None = None


class VisualDelta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    base_hash: str
    target_hash: str
    target_sequence: int = Field(ge=0)
    operations: tuple[DeltaOperation, ...]


def diff_snapshots(base: VisualSnapshot, target: VisualSnapshot) -> VisualDelta:
    operations: list[DeltaOperation] = []
    keys = sorted(set(base.entities) | set(target.entities))
    for entity_id in keys:
        if entity_id not in target.entities:
            operations.append(DeltaOperation(op="remove", entity_id=entity_id))
        elif entity_id not in base.entities:
            operations.append(DeltaOperation(op="add", entity_id=entity_id, value=deepcopy(target.entities[entity_id])))
        elif base.entities[entity_id] != target.entities[entity_id]:
            operations.append(DeltaOperation(op="replace", entity_id=entity_id, value=deepcopy(target.entities[entity_id])))
    return VisualDelta(
        base_hash=base.snapshot_hash,
        target_hash=target.snapshot_hash,
        target_sequence=target.sequence,
        operations=tuple(operations),
    )


def replay_delta(base: VisualSnapshot, delta: VisualDelta) -> VisualSnapshot:
    if base.snapshot_hash != delta.base_hash:
        raise ValueError("visual delta base hash mismatch")
    entities = deepcopy(base.entities)
    for operation in delta.operations:
        if operation.op == "remove":
            entities.pop(operation.entity_id, None)
        else:
            if operation.value is None:
                raise ValueError("add/replace delta requires a value")
            entities[operation.entity_id] = deepcopy(operation.value)
    material = {"sequence": delta.target_sequence, "entities": entities, "bindings": {k: v.model_dump(mode="json") for k, v in sorted(base.bindings.items()) if k in entities}}
    computed_hash = canonical_hash(material)
    if computed_hash != delta.target_hash:
        raise ValueError("visual delta target hash mismatch")
    return VisualSnapshot(
        sequence=delta.target_sequence,
        entities=entities,
        bindings={k: v for k, v in base.bindings.items() if k in entities},
        snapshot_hash=computed_hash,
    )
