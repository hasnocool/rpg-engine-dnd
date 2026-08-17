"""v0.5 transport-neutral client helpers for CLI, live text, TUI, REST, and WebSocket clients."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from .events import Event
from .multiplayer import CampaignSession


@dataclass(frozen=True, slots=True)
class TextFrame:
    sequence: int
    text: str


class LiveTextClient:
    """Render authoritative events without owning or mutating game truth."""

    @staticmethod
    def render(event: Event) -> TextFrame:
        entity = "" if event.entity_id is None else f" [{event.entity_id}]"
        return TextFrame(event.sequence, f"#{event.sequence} {event.kind}{entity}")

    async def stream(self, session: CampaignSession, user_id: str) -> AsyncIterator[TextFrame]:
        while True:
            event = await session.next_event(user_id)
            yield self.render(event)


class CommandMailbox:
    """Non-blocking queue used by text/TUI/WebSocket adapters."""

    def __init__(self, *, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=maxsize)

    async def submit(self, command: dict[str, object]) -> None:
        await self._queue.put(dict(command))

    async def receive(self) -> dict[str, object]:
        return await self._queue.get()
