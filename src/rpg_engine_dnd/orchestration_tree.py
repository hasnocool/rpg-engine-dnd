"""Hierarchical scene authority for worlds, regions, dungeons, floors, and encounters."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class NodeState(StrEnum):
    SLEEPING = "sleeping"
    LOADING = "loading"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class SceneNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    parent_id: str | None = None
    state: NodeState = NodeState.SLEEPING
    child_ids: set[str] = Field(default_factory=set)
    entity_ids: set[str] = Field(default_factory=set)
    background_simulation: bool = False


class SceneTree(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: dict[str, SceneNode] = Field(default_factory=dict)

    def add(self, node: SceneNode) -> None:
        if node.scene_id in self.nodes:
            raise ValueError("scene already exists")
        if node.parent_id is not None and node.parent_id not in self.nodes:
            raise ValueError("scene parent does not exist")
        self.nodes[node.scene_id] = node
        if node.parent_id is not None:
            self.nodes[node.parent_id].child_ids.add(node.scene_id)

    def set_state(self, scene_id: str, state: NodeState) -> None:
        node = self.nodes[scene_id]
        if state == NodeState.ACTIVE and node.parent_id is not None:
            parent = self.nodes[node.parent_id]
            if parent.state not in {NodeState.ACTIVE, NodeState.SUSPENDED}:
                raise ValueError("child cannot activate while parent is inactive")
        node.state = state

    def streamed_entities(self) -> set[str]:
        result: set[str] = set()
        for node in self.nodes.values():
            if node.state == NodeState.ACTIVE or (node.background_simulation and node.state == NodeState.SUSPENDED):
                result.update(node.entity_ids)
        return result
