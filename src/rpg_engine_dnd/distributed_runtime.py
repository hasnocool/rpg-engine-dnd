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
    """Store-backed coordinator with process-safe CAS when the store supports it."""

    def __init__(self, store: object) -> None:
        self.store = store
        self._lock = asyncio.Lock()

    @staticmethod
    def _next_lease(
        previous_raw: dict[str, object] | None,
        *,
        shard_id: str,
        region: str,
        owner_id: str,
        lease_id: str,
        ttl_seconds: int,
    ) -> ShardLease:
        previous = ShardLease.model_validate(previous_raw) if previous_raw else None
        return ShardLease(
            shard_id=shard_id,
            region=region,
            epoch=1 if previous is None else previous.epoch + 1,
            lease_id=lease_id,
            fencing_token=1 if previous is None else previous.fencing_token + 1,
            owner_id=owner_id,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )

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
        compare_and_set = getattr(self.store, "compare_and_set_json", None)
        if compare_and_set is not None:
            for _ in range(16):
                previous_raw = await get_json("world:lease", shard_id)
                lease = self._next_lease(
                    previous_raw,
                    shard_id=shard_id,
                    region=region,
                    owner_id=owner_id,
                    lease_id=lease_id,
                    ttl_seconds=ttl_seconds,
                )
                if await compare_and_set(
                    "world:lease",
                    shard_id,
                    previous_raw,
                    lease.model_dump(mode="json"),
                ):
                    return lease
            raise RuntimeError("shard lease contention exceeded retry budget")

        put_json = getattr(self.store, "put_json")
        async with self._lock:
            previous_raw = await get_json("world:lease", shard_id)
            lease = self._next_lease(
                previous_raw,
                shard_id=shard_id,
                region=region,
                owner_id=owner_id,
                lease_id=lease_id,
                ttl_seconds=ttl_seconds,
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
        compare_and_set = getattr(self.store, "compare_and_set_json", None)
        key = message.idempotency_key
        claim = {"message_id": message.message_id, "message": message.model_dump(mode="json")}
        if compare_and_set is not None:
            if not await compare_and_set("world:message-idempotency", key, None, claim):
                return False
            await put_json("world:message", message.message_id, message.model_dump(mode="json"))
            return True

        async with self._lock:
            existing = await get_json("world:message-idempotency", key)
            if existing is not None:
                return False
            await put_json("world:message-idempotency", key, claim)
            await put_json("world:message", message.message_id, message.model_dump(mode="json"))
            return True

    async def dead_letter(self, message: DurableMessage, reason: str) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json(
            "world:dead-letter",
            message.message_id,
            {"message": message.model_dump(mode="json"), "reason": reason},
        )
