"""v2.0 authoritative campaign scene orchestration and streamed entity projections."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class SceneType(StrEnum):
    EXPLORATION = "exploration"
    ENCOUNTER = "encounter"
    DIALOGUE = "dialogue"
    TRAVEL = "travel"
    DOWNTIME = "downtime"
    SETTLEMENT = "settlement"
    DUNGEON = "dungeon"
    CUSTOM = "custom"


class SceneStatus(StrEnum):
    UNLOADED = "unloaded"
    LOADING = "loading"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: str
    scene_type: SceneType
    status: SceneStatus = SceneStatus.UNLOADED
    entity_ids: set[str] = Field(default_factory=set)
    preload_entity_ids: set[str] = Field(default_factory=set)
    next_scene_ids: tuple[str, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)


_ALLOWED_TRANSITIONS: dict[SceneStatus, set[SceneStatus]] = {
    SceneStatus.UNLOADED: {SceneStatus.LOADING, SceneStatus.ARCHIVED},
    SceneStatus.LOADING: {SceneStatus.ACTIVE, SceneStatus.UNLOADED},
    SceneStatus.ACTIVE: {SceneStatus.SUSPENDED, SceneStatus.RESOLVED},
    SceneStatus.SUSPENDED: {SceneStatus.ACTIVE, SceneStatus.RESOLVED},
    SceneStatus.RESOLVED: {SceneStatus.ARCHIVED},
    SceneStatus.ARCHIVED: set(),
}


class CampaignOrchestrator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: dict[str, Scene] = Field(default_factory=dict)
    active_scene_id: str | None = None
    campaign_metadata: dict[str, object] = Field(default_factory=dict)

    def register(self, scene: Scene) -> None:
        if scene.scene_id in self.scenes:
            raise ValueError("scene already registered")
        self.scenes[scene.scene_id] = scene
        self._persist()

    def transition(self, scene_id: str, status: SceneStatus) -> Scene:
        scene = self.scenes[scene_id]
        if status not in _ALLOWED_TRANSITIONS[scene.status]:
            raise ValueError(f"invalid scene transition {scene.status} -> {status}")
        if status == SceneStatus.ACTIVE:
            if self.active_scene_id is not None and self.active_scene_id != scene_id:
                raise ValueError("another scene is already active")
            self.active_scene_id = scene_id
        elif self.active_scene_id == scene_id and status != SceneStatus.ACTIVE:
            self.active_scene_id = None
        scene.status = status
        self._persist()
        return scene

    def streamed_entity_ids(self) -> set[str]:
        if self.active_scene_id is None:
            return set()
        active = self.scenes[self.active_scene_id]
        result = set(active.entity_ids) | set(active.preload_entity_ids)
        for next_id in active.next_scene_ids:
            candidate = self.scenes.get(next_id)
            if candidate is not None:
                result.update(candidate.preload_entity_ids)
        return result

    def next_scene_candidates(self) -> tuple[Scene, ...]:
        if self.active_scene_id is None:
            return ()
        active = self.scenes[self.active_scene_id]
        return tuple(self.scenes[scene_id] for scene_id in active.next_scene_ids if scene_id in self.scenes)

    def _persist(self) -> None:
        self.campaign_metadata["orchestrator"] = {
            "active_scene_id": self.active_scene_id,
            "scenes": {
                scene_id: scene.model_dump(mode="json")
                for scene_id, scene in sorted(self.scenes.items())
            },
        }
