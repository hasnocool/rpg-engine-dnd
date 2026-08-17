"""v3.0 deterministic shard registry, routing, Lamport messages, and two-phase entity handoff."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash


class ShardStatus(StrEnum):
    ACTIVE = "active"
    DRAINING = "draining"
    OFFLINE = "offline"


class WorldShard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shard_id: str
    region: str
    capacity: int = Field(gt=0)
    load: int = Field(default=0, ge=0)
    status: ShardStatus = ShardStatus.ACTIVE
    heartbeat_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.load)


class ShardRegistry:
    def __init__(self) -> None:
        self._shards: dict[str, WorldShard] = {}
        self._lock = asyncio.Lock()

    async def heartbeat(self, shard: WorldShard) -> None:
        async with self._lock:
            self._shards[shard.shard_id] = shard.model_copy(update={"heartbeat_at": datetime.now(UTC)})

    async def active(self, *, region: str | None = None, max_age_seconds: int = 30) -> list[WorldShard]:
        cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
        async with self._lock:
            return [
                shard.model_copy(deep=True)
                for shard in self._shards.values()
                if shard.status == ShardStatus.ACTIVE
                and shard.heartbeat_at >= cutoff
                and shard.available > 0
                and (region is None or shard.region == region)
            ]

    async def expire(self, *, max_age_seconds: int = 30) -> list[str]:
        cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
        expired: list[str] = []
        async with self._lock:
            for shard in self._shards.values():
                if shard.heartbeat_at < cutoff and shard.status != ShardStatus.OFFLINE:
                    shard.status = ShardStatus.OFFLINE
                    expired.append(shard.shard_id)
        return sorted(expired)

    async def route(self, entity_key: str, *, region: str) -> WorldShard:
        candidates = await self.active(region=region)
        if not candidates:
            raise ValueError(f"no active shard in region {region}")

        def score(shard: WorldShard) -> int:
            digest = hashlib.sha256(f"{region}\0{entity_key}\0{shard.shard_id}".encode()).digest()
            raw = int.from_bytes(digest, "big")
            return raw * shard.available // shard.capacity

        return max(candidates, key=lambda shard: (score(shard), shard.shard_id))

    async def rebalance_plan(self, entity_keys: list[str], *, region: str, current: dict[str, str]) -> list[tuple[str, str, str | None]]:
        plan: list[tuple[str, str, str | None]] = []
        for entity_key in sorted(entity_keys):
            target = await self.route(entity_key, region=region)
            previous = current.get(entity_key)
            if previous != target.shard_id:
                plan.append((entity_key, target.shard_id, previous))
        return plan


class LamportClock:
    def __init__(self) -> None:
        self.value = 0
        self._lock = asyncio.Lock()

    async def tick(self, observed: int | None = None) -> int:
        async with self._lock:
            if observed is not None:
                self.value = max(self.value, observed)
            self.value += 1
            return self.value


class CrossShardMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    message_id: str
    idempotency_key: str
    source_shard: str
    target_shard: str
    lamport: int = Field(ge=1)
    kind: str
    payload: dict[str, object] = Field(default_factory=dict)


class MessageLedger:
    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._messages: list[CrossShardMessage] = []
        self._lock = asyncio.Lock()

    async def accept(self, message: CrossShardMessage) -> bool:
        async with self._lock:
            if message.idempotency_key in self._seen:
                return False
            self._seen.add(message.idempotency_key)
            self._messages.append(message)
            self._messages.sort(key=lambda item: (item.lamport, item.source_shard, item.message_id))
            return True

    async def ordered(self) -> list[CrossShardMessage]:
        async with self._lock:
            return list(self._messages)


class TransferStatus(StrEnum):
    PREPARED = "prepared"
    ACCEPTED = "accepted"
    COMMITTED = "committed"
    ABORTED = "aborted"


class EntityTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transfer_id: str
    entity_id: str
    source_shard: str
    target_shard: str
    payload: dict[str, object]
    payload_hash: str
    status: TransferStatus = TransferStatus.PREPARED


class TransferManager:
    def __init__(self) -> None:
        self._transfers: dict[str, EntityTransfer] = {}
        self._committed_entities: dict[tuple[str, str], str] = {}
        self._lock = asyncio.Lock()

    async def prepare(self, transfer_id: str, entity_id: str, source_shard: str, target_shard: str, payload: dict[str, object]) -> EntityTransfer:
        transfer = EntityTransfer(
            transfer_id=transfer_id,
            entity_id=entity_id,
            source_shard=source_shard,
            target_shard=target_shard,
            payload=dict(payload),
            payload_hash=canonical_hash(payload),
        )
        async with self._lock:
            existing = self._transfers.get(transfer_id)
            if existing is not None:
                if existing.payload_hash != transfer.payload_hash:
                    raise ValueError("transfer id reused with different payload")
                return existing.model_copy(deep=True)
            self._transfers[transfer_id] = transfer
            return transfer.model_copy(deep=True)

    async def accept(self, transfer_id: str, payload: dict[str, object]) -> EntityTransfer:
        async with self._lock:
            transfer = self._transfers[transfer_id]
            if transfer.status != TransferStatus.PREPARED:
                raise ValueError("transfer is not prepared")
            if canonical_hash(payload) != transfer.payload_hash:
                raise ValueError("transfer payload verification failed")
            transfer.status = TransferStatus.ACCEPTED
            return transfer.model_copy(deep=True)

    async def commit(self, transfer_id: str) -> EntityTransfer:
        async with self._lock:
            transfer = self._transfers[transfer_id]
            if transfer.status == TransferStatus.COMMITTED:
                return transfer.model_copy(deep=True)
            if transfer.status != TransferStatus.ACCEPTED:
                raise ValueError("transfer must be accepted before commit")
            guard = (transfer.target_shard, transfer.entity_id)
            previous = self._committed_entities.get(guard)
            if previous is not None and previous != transfer_id:
                raise ValueError("entity already committed by another transfer")
            self._committed_entities[guard] = transfer_id
            transfer.status = TransferStatus.COMMITTED
            return transfer.model_copy(deep=True)

    async def abort(self, transfer_id: str) -> EntityTransfer:
        async with self._lock:
            transfer = self._transfers[transfer_id]
            if transfer.status == TransferStatus.COMMITTED:
                raise ValueError("committed transfer cannot be aborted")
            transfer.status = TransferStatus.ABORTED
            return transfer.model_copy(deep=True)

    async def restore_payload(self, transfer_id: str) -> dict[str, object]:
        async with self._lock:
            transfer = self._transfers[transfer_id]
            if transfer.status != TransferStatus.COMMITTED:
                raise ValueError("transfer is not committed")
            if canonical_hash(transfer.payload) != transfer.payload_hash:
                raise ValueError("stored transfer payload corrupted")
            return dict(transfer.payload)


class PersistentShardCoordinator:
    """Persists shard, assignment, transfer, and cross-shard metadata via shared stores."""

    def __init__(self, store: object) -> None:
        self.store = store

    async def save_shard(self, shard: WorldShard) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json("world:shard", shard.shard_id, shard.model_dump(mode="json"))

    async def save_assignment(self, entity_key: str, shard_id: str, region: str) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json("world:assignment", entity_key, {"entity_key": entity_key, "shard_id": shard_id, "region": region})

    async def save_transfer(self, transfer: EntityTransfer) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json("world:transfer", transfer.transfer_id, transfer.model_dump(mode="json"))

    async def save_message(self, message: CrossShardMessage) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json("world:message", message.message_id, message.model_dump(mode="json"))
