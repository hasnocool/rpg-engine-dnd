"""v1.0 hosted campaigns, community registry, marketplace metadata, and public API metadata."""

from __future__ import annotations

import asyncio
from pydantic import BaseModel, ConfigDict, Field

from .creator import CampaignTemplate
from .models import Entity, World


class HostedCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str
    template_id: str
    owner_id: str
    metadata: dict[str, object] = Field(default_factory=dict)


class MarketplaceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_id: str
    version: str
    title: str
    author: str
    content_hash: str
    metadata: dict[str, object] = Field(default_factory=dict)


class CommunityContentRegistry:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], MarketplaceEntry] = {}
        self._lock = asyncio.Lock()

    async def publish(self, entry: MarketplaceEntry) -> None:
        async with self._lock:
            self._entries[(entry.package_id, entry.version)] = entry.model_copy(deep=True)

    async def get(self, package_id: str, version: str) -> MarketplaceEntry:
        async with self._lock:
            return self._entries[(package_id, version)].model_copy(deep=True)

    async def list(self) -> list[MarketplaceEntry]:
        async with self._lock:
            return [self._entries[key].model_copy(deep=True) for key in sorted(self._entries)]


class CampaignFactory:
    @staticmethod
    def instantiate(template: CampaignTemplate) -> World:
        entities: dict[str, Entity] = {}
        for raw in template.entities:
            entity = Entity.model_validate(raw)
            entities[entity.entity_id] = entity
        return World(entities=entities)


ENGINE_API_VERSION = "3.0"
PUBLIC_API_INFO = {
    "title": "rpg-engine-dnd",
    "version": ENGINE_API_VERSION,
    "contract": "versioned authoritative command/event platform API",
}
