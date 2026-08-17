"""v1.7 production hosting contracts, workers, leases, placement, reconnect tickets, and PostgreSQL."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_json


class AsyncPersistence(Protocol):
    async def initialize(self) -> None: ...
    async def put_json(self, namespace: str, key: str, value: dict[str, object]) -> None: ...
    async def get_json(self, namespace: str, key: str) -> dict[str, object] | None: ...
    async def list_json(self, namespace: str) -> dict[str, dict[str, object]]: ...


MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS platform_json (
        namespace TEXT NOT NULL,
        key TEXT NOT NULL,
        payload JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY(namespace, key)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS campaign_leases (
        campaign_id TEXT PRIMARY KEY,
        worker_id TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    );
    """,
)


class AsyncPostgresStore:
    """Asyncpg-backed persistence. Network/database calls never run synchronously."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: Any = None

    async def initialize(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(self.dsn)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                for migration in MIGRATIONS:
                    await connection.execute(migration)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    def _require_pool(self) -> Any:
        if self._pool is None:
            raise RuntimeError("PostgreSQL store is not initialized")
        return self._pool

    async def put_json(self, namespace: str, key: str, value: dict[str, object]) -> None:
        pool = self._require_pool()
        payload = canonical_json(value)
        async with pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO platform_json(namespace, key, payload)
                VALUES($1, $2, $3::jsonb)
                ON CONFLICT(namespace, key)
                DO UPDATE SET payload=excluded.payload, updated_at=NOW()
                """,
                namespace,
                key,
                payload,
            )

    async def get_json(self, namespace: str, key: str) -> dict[str, object] | None:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT payload FROM platform_json WHERE namespace=$1 AND key=$2",
                namespace,
                key,
            )
        if row is None:
            return None
        return dict(row["payload"])

    async def list_json(self, namespace: str) -> dict[str, dict[str, object]]:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT key, payload FROM platform_json WHERE namespace=$1 ORDER BY key",
                namespace,
            )
        return {str(row["key"]): dict(row["payload"]) for row in rows}

    async def acquire_lease(self, campaign_id: str, worker_id: str, ttl_seconds: int = 30) -> bool:
        pool = self._require_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO campaign_leases(campaign_id, worker_id, expires_at)
                VALUES($1, $2, NOW() + ($3 * INTERVAL '1 second'))
                ON CONFLICT(campaign_id) DO UPDATE SET
                    worker_id=excluded.worker_id,
                    expires_at=excluded.expires_at
                WHERE campaign_leases.expires_at < NOW() OR campaign_leases.worker_id=$2
                RETURNING worker_id
                """,
                campaign_id,
                worker_id,
                ttl_seconds,
            )
        return row is not None and row["worker_id"] == worker_id


class WorkerRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str
    capacity: int = Field(gt=0)
    active_campaigns: int = Field(default=0, ge=0)
    last_heartbeat: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.active_campaigns)


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerRecord] = {}
        self._lock = asyncio.Lock()

    async def heartbeat(self, record: WorkerRecord) -> None:
        async with self._lock:
            self._workers[record.worker_id] = record.model_copy(update={"last_heartbeat": datetime.now(UTC)})

    async def healthy(self, *, max_age_seconds: int = 30) -> list[WorkerRecord]:
        cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
        async with self._lock:
            return [
                record.model_copy(deep=True)
                for record in self._workers.values()
                if record.last_heartbeat >= cutoff and record.available > 0
            ]


class RendezvousPlacement:
    @staticmethod
    def choose(campaign_id: str, workers: list[WorkerRecord]) -> WorkerRecord:
        candidates = [worker for worker in workers if worker.available > 0]
        if not candidates:
            raise ValueError("no worker capacity")

        def score(worker: WorkerRecord) -> int:
            digest = hashlib.sha256(f"{campaign_id}\0{worker.worker_id}".encode()).digest()
            raw = int.from_bytes(digest, "big")
            return raw * worker.available // worker.capacity

        return max(candidates, key=lambda worker: (score(worker), worker.worker_id))


class ReconnectTicket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    token_hash: str
    campaign_id: str
    user_id: str
    event_sequence: int = Field(ge=0)


class ReconnectTicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, ReconnectTicket] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def issue(self, campaign_id: str, user_id: str, event_sequence: int) -> str:
        token = secrets.token_urlsafe(32)
        ticket = ReconnectTicket(
            token_hash=self._hash(token),
            campaign_id=campaign_id,
            user_id=user_id,
            event_sequence=event_sequence,
        )
        async with self._lock:
            self._tickets[ticket.token_hash] = ticket
        return token

    async def consume_and_rotate(self, token: str, *, new_sequence: int) -> tuple[ReconnectTicket, str]:
        token_hash = self._hash(token)
        async with self._lock:
            ticket = self._tickets.pop(token_hash)
        new_token = await self.issue(ticket.campaign_id, ticket.user_id, new_sequence)
        return ticket, new_token
