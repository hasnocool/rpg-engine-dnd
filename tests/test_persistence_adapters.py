# tests/test_persistence_adapters.py
from copy import deepcopy

import pytest

from rpg_engine_dnd.distribution import PackageRelease, PersistentDistributionRegistry, SemVer
from rpg_engine_dnd.event_sourcing import EventJournal, JournalPersistenceBridge
from rpg_engine_dnd.hosting import ReconnectTicketStore, RendezvousPlacement, WorkerRecord, WorkerRegistry
from rpg_engine_dnd.sharding import (
    CrossShardMessage,
    PersistentShardCoordinator,
    WorldShard,
)
from rpg_engine_dnd.studio import StudioProject, StudioRepository


class MemoryAsyncStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, object]]] = {}

    async def initialize(self) -> None:
        return None

    async def put_json(self, namespace: str, key: str, value: dict[str, object]) -> None:
        self.data.setdefault(namespace, {})[key] = deepcopy(value)

    async def get_json(self, namespace: str, key: str) -> dict[str, object] | None:
        value = self.data.get(namespace, {}).get(key)
        return None if value is None else deepcopy(value)

    async def list_json(self, namespace: str) -> dict[str, dict[str, object]]:
        return deepcopy(self.data.get(namespace, {}))


@pytest.mark.asyncio
async def test_shared_persistence_contract_across_v13_v18_v25_v30() -> None:
    store = MemoryAsyncStore()

    journal = EventJournal({"turn": 0})
    entry = journal.append(
        command_id="turn:1",
        event_kind="turn.advanced",
        before={"turn": 0},
        after={"turn": 1},
    )
    journal_store = JournalPersistenceBridge(store, "campaign-1")
    await journal_store.append(entry)
    assert (await journal_store.load())[0].entry_hash == entry.entry_hash

    project = StudioProject(project_id="p1", name="Project", document={"map": {"nodes": []}})
    project.snapshot()
    studio_store = StudioRepository(store)
    await studio_store.save(project)
    restored = await studio_store.load("p1")
    assert restored is not None
    assert restored.revisions[0].content_hash == project.revisions[0].content_hash

    distribution = PersistentDistributionRegistry(store, engine_version="3.0.0")
    await distribution.publish(
        PackageRelease(
            package_id="pack",
            version="1.0.0",
            content_hash="abc",
        )
    )
    lock = await distribution.resolve("pack")
    reloaded = PersistentDistributionRegistry(store, engine_version="3.0.0")
    await reloaded.load()
    assert (await reloaded.resolve("pack")).lock_hash == lock.lock_hash

    coordinator = PersistentShardCoordinator(store)
    shard = WorldShard(shard_id="west-1", region="west", capacity=10)
    await coordinator.save_shard(shard)
    await coordinator.save_assignment("hero", "west-1", "west")
    message = CrossShardMessage(
        message_id="m1",
        idempotency_key="idempotent-1",
        source_shard="west-1",
        target_shard="west-2",
        lamport=1,
        kind="entity.notice",
        payload={"entity_id": "hero"},
    )
    await coordinator.save_message(message)
    assert store.data["world:shard"]["west-1"]["region"] == "west"
    assert store.data["world:assignment"]["hero"]["shard_id"] == "west-1"
    assert store.data["world:message"]["m1"]["lamport"] == 1


@pytest.mark.asyncio
async def test_worker_placement_and_reconnect_rotation() -> None:
    registry = WorkerRegistry()
    await registry.heartbeat(WorkerRecord(worker_id="w1", capacity=4, active_campaigns=1))
    await registry.heartbeat(WorkerRecord(worker_id="w2", capacity=8, active_campaigns=1))
    healthy = await registry.healthy()
    first = RendezvousPlacement.choose("campaign-42", healthy)
    second = RendezvousPlacement.choose("campaign-42", healthy)
    assert first.worker_id == second.worker_id

    tickets = ReconnectTicketStore()
    token = await tickets.issue("campaign-42", "u1", 10)
    old, rotated = await tickets.consume_and_rotate(token, new_sequence=12)
    assert old.event_sequence == 10
    assert rotated != token
    with pytest.raises(KeyError):
        await tickets.consume_and_rotate(token, new_sequence=13)


def test_semver_prerelease_precedence() -> None:
    assert SemVer.parse("1.0.0-alpha") < SemVer.parse("1.0.0")
    assert SemVer.parse("1.0.0-alpha.1") < SemVer.parse("1.0.0-alpha.beta")
    assert SemVer.parse("1.0.0-beta.2") < SemVer.parse("1.0.0-beta.11")
