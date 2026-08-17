"""v0.6 Godot 2D/3D visual adapter bindings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .models import World


class SceneAssetBinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: str
    scene_path: str
    sprite_path: str | None = None
    model_path: str | None = None
    animations: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)


class GodotEntityState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: str
    binding: SceneAssetBinding | None = None
    components: dict[str, dict[str, object]] = Field(default_factory=dict)


class GodotBridge:
    """Produces engine-neutral payloads consumable by Godot 2D or 3D clients."""

    def __init__(self, bindings: list[SceneAssetBinding] | None = None) -> None:
        self.bindings = {item.entity_id: item for item in (bindings or [])}

    def bind(self, binding: SceneAssetBinding) -> None:
        self.bindings[binding.entity_id] = binding

    def project(self, world: World) -> list[GodotEntityState]:
        return [
            GodotEntityState(
                entity_id=entity_id,
                binding=self.bindings.get(entity_id),
                components=entity.model_dump(mode="json")["components"],
            )
            for entity_id, entity in sorted(world.entities.items())
        ]


class Godot2DBridge(GodotBridge):
    """Named 2D adapter preserving the shared transport-neutral binding contract."""


class Godot3DBridge(GodotBridge):
    """Named 3D adapter preserving the shared transport-neutral binding contract."""
