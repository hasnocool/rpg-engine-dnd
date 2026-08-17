"""Durable shard epochs, fencing leases, idempotent messages, retries, and transfer leases."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class LeaseStatus(StrEnum):
    ACTIVE = "active"
    DRAINING = "draining"
    EXPIRED = "expired"


class ShardLease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    shard_id: str
    region: str
    epoch: int = Field(ge=1)
    lease_id: str
    fencing_token: int = Field(ge=1)
    owner_id: str
    expires_at: datetime
    status: LeaseStatus = LeaseStatus.ACTIVE

    def assert_valid(self, *, now: datetime | None = None) -> None:
        current = datetime.now(UTC) if now is None else now
        if self.status != LeaseStatus.ACTIVE or self.expires_at <= current:
            raise ValueError("shard lease is not active")


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    max_attempts: int = Field(default=5, ge=1)
    base_delay_seconds: float = Field(default=0.25, ge=0)
    max_delay_seconds: float = Field(default=30, ge=0)

    def delay(self, attempt: int) -> float:
        return min(self.max_delay_seconds, self.base_delay_seconds * (2 ** max(0, attempt - 1)))


class DurableMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    message_id: str
    idempotency_key: str
    source_shard: str
    target_shard: str
    sequence: int = Field(ge=1)
    kind: str
    payload: dict[str, object] = Field(default_factory=dict)
    attempts: int = Field(default=0, ge=0)
    acknowledged: bool = False


class TransferLease(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    transfer_id: str
    entity_id: str
    source_shard: str
    target_shard: str
    source_epoch: int = Field(ge=1)
    target_epoch: int = Field(ge=1)
    fencing_token: int = Field(ge=1)
    expires_at: datetime


class DurableShardCoordinator:
    """Store-backed coordinator using the repository's async JSON persistence contract."""

    def __init__(self, store: object) -> None:
        self.store = store
        self._lock = asyncio.Lock()

    async def acquire_lease(
        self,
        *,
        shard_id: str,
        region: str,
        owner_id: str,
        lease_id: str,
        ttl_seconds: int = 30,
    ) -> ShardLease:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        get_json = getattr(self.store, "get_json")
        put_json = getattr(self.store, "put_json")
        async with self._lock:
            previous_raw = await get_json("world:lease", shard_id)
            previous = ShardLease.model_validate(previous_raw) if previous_raw else None
            epoch = 1 if previous is None else previous.epoch + 1
            token = 1 if previous is None else previous.fencing_token + 1
            lease = ShardLease(
                shard_id=shard_id,
                region=region,
                epoch=epoch,
                lease_id=lease_id,
                fencing_token=token,
                owner_id=owner_id,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
            await put_json("world:lease", shard_id, lease.model_dump(mode="json"))
            return lease

    async def assert_fence(self, shard_id: str, fencing_token: int) -> ShardLease:
        get_json = getattr(self.store, "get_json")
        raw = await get_json("world:lease", shard_id)
        if raw is None:
            raise ValueError("shard lease does not exist")
        lease = ShardLease.model_validate(raw)
        lease.assert_valid()
        if fencing_token != lease.fencing_token:
            raise ValueError("stale shard fencing token")
        return lease

    async def publish(self, message: DurableMessage) -> bool:
        get_json = getattr(self.store, "get_json")
        put_json = getattr(self.store, "put_json")
        key = message.idempotency_key
        async with self._lock:
            existing = await get_json("world:message-idempotency", key)
            if existing is not None:
                return False
            await put_json("world:message", message.message_id, message.model_dump(mode="json"))
            await put_json("world:message-idempotency", key, {"message_id": message.message_id})
            return True

    async def dead_letter(self, message: DurableMessage, reason: str) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json(
            "world:dead-letter",
            message.message_id,
            {"message": message.model_dump(mode="json"), "reason": reason},
        )
