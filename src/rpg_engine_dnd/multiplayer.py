"""v0.8 authoritative campaign sessions, parties, spectators, ownership, and hosting."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from pydantic import BaseModel, ConfigDict, Field

from .events import Event


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid")
    party_id: str
    member_ids: set[str] = Field(default_factory=set)


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    spectator: bool = False
    owned_actor_ids: set[str] = Field(default_factory=set)


class CampaignSession:
    """Concurrency-safe in-memory authoritative session boundary."""

    def __init__(self, campaign_id: str) -> None:
        if not campaign_id:
            raise ValueError("campaign_id must not be empty")
        self.campaign_id = campaign_id
        self.participants: dict[str, Participant] = {}
        self.parties: dict[str, Party] = {}
        self._subscribers: dict[str, asyncio.Queue[Event]] = defaultdict(asyncio.Queue)
        self._lock = asyncio.Lock()

    async def join(self, participant: Participant) -> None:
        async with self._lock:
            self.participants[participant.user_id] = participant.model_copy(deep=True)
            self._subscribers.setdefault(participant.user_id, asyncio.Queue())

    async def leave(self, user_id: str) -> None:
        async with self._lock:
            self.participants.pop(user_id, None)
            self._subscribers.pop(user_id, None)

    async def assign_actor(self, user_id: str, actor_id: str) -> None:
        async with self._lock:
            participant = self.participants[user_id]
            if participant.spectator:
                raise PermissionError("spectators cannot own actors")
            for other in self.participants.values():
                if other.user_id != user_id and actor_id in other.owned_actor_ids:
                    raise ValueError("actor already owned")
            participant.owned_actor_ids.add(actor_id)

    async def require_actor_control(self, user_id: str, actor_id: str) -> None:
        async with self._lock:
            participant = self.participants[user_id]
            if participant.spectator or actor_id not in participant.owned_actor_ids:
                raise PermissionError("actor is not controlled by participant")

    async def create_party(self, party: Party) -> None:
        async with self._lock:
            self.parties[party.party_id] = party.model_copy(deep=True)

    async def publish(self, event: Event) -> None:
        async with self._lock:
            queues = list(self._subscribers.values())
        for queue in queues:
            queue.put_nowait(event)

    async def next_event(self, user_id: str, *, wait_seconds: float | None = None) -> Event:
        async with self._lock:
            queue = self._subscribers[user_id]
        if wait_seconds is None:
            return await queue.get()
        async with asyncio.timeout(wait_seconds):
            return await queue.get()


class CampaignHost:
    def __init__(self) -> None:
        self._sessions: dict[str, CampaignSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, campaign_id: str) -> CampaignSession:
        async with self._lock:
            session = self._sessions.get(campaign_id)
            if session is None:
                session = CampaignSession(campaign_id)
                self._sessions[campaign_id] = session
            return session

    async def list_campaigns(self) -> list[str]:
        async with self._lock:
            return sorted(self._sessions)
