"""v0.8 authoritative campaign sessions, parties, spectators, ownership, and hosting."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field

from .events import Event


class SessionPermission(StrEnum):
    PLAY = "play"
    MANAGE_PARTY = "manage-party"
    GM_DELEGATE = "gm-delegate"
    SPECTATE = "spectate"


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid")
    party_id: str
    member_ids: set[str] = Field(default_factory=set)
    manager_ids: set[str] = Field(default_factory=set)


class Participant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    spectator: bool = False
    owned_actor_ids: set[str] = Field(default_factory=set)
    permissions: set[SessionPermission] = Field(default_factory=lambda: {SessionPermission.PLAY})

    def has_permission(self, permission: SessionPermission) -> bool:
        if self.spectator and permission == SessionPermission.PLAY:
            return False
        return permission in self.permissions


class CampaignSession:
    """Concurrency-safe authoritative session boundary with actor-level serialization."""

    def __init__(
        self,
        campaign_id: str,
        *,
        command_rate_limit: int = 60,
        command_rate_window_seconds: float = 10.0,
    ) -> None:
        if not campaign_id:
            raise ValueError("campaign_id must not be empty")
        if command_rate_limit < 1 or command_rate_window_seconds <= 0:
            raise ValueError("invalid command rate limit")
        self.campaign_id = campaign_id
        self.participants: dict[str, Participant] = {}
        self.parties: dict[str, Party] = {}
        self._subscribers: dict[str, asyncio.Queue[Event]] = defaultdict(asyncio.Queue)
        self._actor_locks: dict[str, asyncio.Lock] = {}
        self._command_times: dict[str, list[float]] = defaultdict(list)
        self._command_sequence = 0
        self._rate_limit = command_rate_limit
        self._rate_window = command_rate_window_seconds
        self._lock = asyncio.Lock()

    async def join(self, participant: Participant) -> None:
        async with self._lock:
            if participant.spectator:
                participant = participant.model_copy(
                    update={"permissions": set(participant.permissions) | {SessionPermission.SPECTATE}}
                )
            self.participants[participant.user_id] = participant.model_copy(deep=True)
            self._subscribers.setdefault(participant.user_id, asyncio.Queue())

    async def leave(self, user_id: str) -> None:
        async with self._lock:
            self.participants.pop(user_id, None)
            self._subscribers.pop(user_id, None)
            self._command_times.pop(user_id, None)

    async def assign_actor(self, user_id: str, actor_id: str) -> None:
        async with self._lock:
            participant = self.participants[user_id]
            if participant.spectator or not participant.has_permission(SessionPermission.PLAY):
                raise PermissionError("participant cannot own actors")
            for other in self.participants.values():
                if other.user_id != user_id and actor_id in other.owned_actor_ids:
                    raise ValueError("actor already owned")
            participant.owned_actor_ids.add(actor_id)
            self._actor_locks.setdefault(actor_id, asyncio.Lock())

    async def require_actor_control(self, user_id: str, actor_id: str) -> None:
        async with self._lock:
            participant = self.participants[user_id]
            if participant.spectator or actor_id not in participant.owned_actor_ids:
                raise PermissionError("actor is not controlled by participant")

    async def require_permission(self, user_id: str, permission: SessionPermission) -> None:
        async with self._lock:
            participant = self.participants[user_id]
            if not participant.has_permission(permission):
                raise PermissionError(f"participant lacks permission: {permission.value}")

    async def delegate_gm(self, user_id: str, *, enabled: bool = True) -> None:
        async with self._lock:
            participant = self.participants[user_id]
            if enabled:
                participant.permissions.add(SessionPermission.GM_DELEGATE)
            else:
                participant.permissions.discard(SessionPermission.GM_DELEGATE)

    async def create_party(self, party: Party) -> None:
        async with self._lock:
            if party.party_id in self.parties:
                raise ValueError("party already exists")
            self.parties[party.party_id] = party.model_copy(deep=True)

    async def update_party_members(self, user_id: str, party_id: str, member_ids: set[str]) -> None:
        async with self._lock:
            participant = self.participants[user_id]
            party = self.parties[party_id]
            if user_id not in party.manager_ids and not participant.has_permission(SessionPermission.GM_DELEGATE):
                raise PermissionError("participant cannot manage this party")
            party.member_ids = set(member_ids)

    def _consume_rate_limit_locked(self, user_id: str) -> None:
        now = monotonic()
        cutoff = now - self._rate_window
        recent = [timestamp for timestamp in self._command_times[user_id] if timestamp >= cutoff]
        if len(recent) >= self._rate_limit:
            self._command_times[user_id] = recent
            raise RuntimeError("participant command rate limit exceeded")
        recent.append(now)
        self._command_times[user_id] = recent

    async def next_command_sequence(self, user_id: str, *, expected_world_revision: int | None, actual_world_revision: int) -> int:
        async with self._lock:
            if user_id not in self.participants:
                raise PermissionError("participant is not in campaign")
            if expected_world_revision is not None and expected_world_revision != actual_world_revision:
                raise ValueError(
                    f"stale world revision: expected {expected_world_revision}, actual {actual_world_revision}"
                )
            self._consume_rate_limit_locked(user_id)
            self._command_sequence += 1
            return self._command_sequence

    @asynccontextmanager
    async def actor_command(
        self,
        user_id: str,
        actor_id: str,
        *,
        expected_world_revision: int | None,
        actual_world_revision: int,
    ) -> AsyncIterator[int]:
        """Serialize one actor's commands without holding the session lock while executing."""
        async with self._lock:
            participant = self.participants[user_id]
            if participant.spectator or actor_id not in participant.owned_actor_ids:
                raise PermissionError("actor is not controlled by participant")
            if expected_world_revision is not None and expected_world_revision != actual_world_revision:
                raise ValueError(
                    f"stale world revision: expected {expected_world_revision}, actual {actual_world_revision}"
                )
            self._consume_rate_limit_locked(user_id)
            self._command_sequence += 1
            sequence = self._command_sequence
            actor_lock = self._actor_locks.setdefault(actor_id, asyncio.Lock())
        async with actor_lock:
            yield sequence

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
