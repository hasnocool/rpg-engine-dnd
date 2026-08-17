"""v0.9 creator models, safe validation knobs, and deterministic mod-package ZIPs."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_json


class CampaignTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str
    name: str
    starting_scene: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MapDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class CreatureDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    creature_id: str
    name: str
    stats: dict[str, int] = Field(default_factory=dict)
    tags: set[str] = Field(default_factory=set)


class SpellDocument(BaseModel):
    """Structured spell metadata without copied rulebook prose."""

    model_config = ConfigDict(extra="forbid")
    spell_id: str
    name: str
    level: int = Field(default=0, ge=0, le=20)
    school: str | None = None
    tags: set[str] = Field(default_factory=set)
    rule_graph_id: str | None = None


class QuestObjectiveDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_id: str
    event_kind: str
    target: int = Field(default=1, ge=1)


class QuestDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest_id: str
    title: str
    objectives: list[QuestObjectiveDocument] = Field(default_factory=list)
    tags: set[str] = Field(default_factory=set)


class RulesKnobs(BaseModel):
    """Bounded creator-facing settings; arbitrary code execution is deliberately absent."""

    model_config = ConfigDict(extra="forbid")
    max_level: int = Field(default=20, ge=1, le=100)
    critical_multiplier: int = Field(default=2, ge=1, le=10)
    diagonal_cost: float = Field(default=1.0, ge=1.0, le=2.0)
    death_saves_enabled: bool = True


class ModManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str
    version: str
    engine_constraint: str = ">=0.9"
    files: dict[str, str] = Field(default_factory=dict)


class ContentValidator:
    def validate_template(self, template: CampaignTemplate) -> list[str]:
        errors: list[str] = []
        if not template.entities:
            errors.append("campaign template has no starting entities")
        if not template.starting_scene:
            errors.append("campaign template has no starting scene")
        return errors

    def validate_rules(self, rules: RulesKnobs) -> list[str]:
        return [] if rules.max_level >= 1 else ["max_level must be positive"]


class ModPackage:
    """Safe deterministic ZIP packaging. Disk/ZIP work runs off the event-loop thread."""

    @staticmethod
    async def build(manifest: ModManifest, files: dict[str, bytes]) -> bytes:
        return await asyncio.to_thread(ModPackage._build_sync, manifest, files)

    @staticmethod
    def _build_sync(manifest: ModManifest, files: dict[str, bytes]) -> bytes:
        file_hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
        resolved = manifest.model_copy(update={"files": file_hashes})
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            info = zipfile.ZipInfo("manifest.json")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            archive.writestr(info, canonical_json(resolved.model_dump(mode="json")))
            for name, data in sorted(files.items()):
                if name.startswith("/") or ".." in name.split("/"):
                    raise ValueError("unsafe package path")
                info = zipfile.ZipInfo(name)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                archive.writestr(info, data)
        return buffer.getvalue()

    @staticmethod
    async def inspect(payload: bytes) -> tuple[ModManifest, dict[str, bytes]]:
        return await asyncio.to_thread(ModPackage._inspect_sync, payload)

    @staticmethod
    def _inspect_sync(payload: bytes) -> tuple[ModManifest, dict[str, bytes]]:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            names = archive.namelist()
            if "manifest.json" not in names:
                raise ValueError("package has no manifest")
            manifest = ModManifest.model_validate(json.loads(archive.read("manifest.json")))
            files: dict[str, bytes] = {}
            for name in names:
                if name == "manifest.json":
                    continue
                if name.startswith("/") or ".." in name.split("/"):
                    raise ValueError("unsafe package path")
                files[name] = archive.read(name)
            expected = manifest.files
            actual = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
            if expected != actual:
                raise ValueError("package hash verification failed")
            return manifest, files
