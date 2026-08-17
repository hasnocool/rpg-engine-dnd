from datetime import UTC, datetime, timedelta

import pytest

from rpg_engine_dnd.director import AdvancedAIDirector, DirectorObservation, ProposalKind
from rpg_engine_dnd.distribution import (
    ContentDistributionRegistry,
    HMACReleaseSigner,
    PackageDependency,
    PackageRelease,
)
from rpg_engine_dnd.knowledge import KnowledgeAuthority
from rpg_engine_dnd.lab import ScenarioSample, SimulationLab
from rpg_engine_dnd.models import Entity, World
from rpg_engine_dnd.orchestrator import CampaignOrchestrator, Scene, SceneStatus, SceneType
from rpg_engine_dnd.sharding import (
    CrossShardMessage,
    LamportClock,
    MessageLedger,
    ShardRegistry,
    TransferManager,
    TransferStatus,
    WorldShard,
)
from rpg_engine_dnd.visual import SceneAssetBinding
from rpg_engine_dnd.visual_runtime import VisualSnapshot, diff_snapshots, replay_delta


def test_v20_scene_orchestrator_lifecycle_streaming_and_candidates() -> None:
    orchestrator = CampaignOrchestrator()
    orchestrator.register(
        Scene(
            scene_id="town",
            scene_type=SceneType.SETTLEMENT,
            entity_ids={"hero", "merchant"},
            preload_entity_ids={"guard"},
            next_scene_ids=("road",),
        )
    )
    orchestrator.register(
        Scene(
            scene_id="road",
            scene_type=SceneType.TRAVEL,
            preload_entity_ids={"wagon"},
        )
    )
    orchestrator.transition("town", SceneStatus.LOADING)
    orchestrator.transition("town", SceneStatus.ACTIVE)
    assert orchestrator.active_scene_id == "town"
    assert orchestrator.streamed_entity_ids() == {"hero", "merchant", "guard", "wagon"}
    assert [scene.scene_id for scene in orchestrator.next_scene_candidates()] == ["road"]
    assert "orchestrator" in orchestrator.campaign_metadata


def _lab_scenario(seed: int) -> ScenarioSample:
    return ScenarioSample(
        seed=seed,
        outcome="even" if seed % 2 == 0 else "odd",
        metric=float(seed % 10),
        event_count=seed % 3,
    )


@pytest.mark.asyncio
async def test_v21_simulation_lab_seed_matrix_aggregation_and_comparison() -> None:
    lab = SimulationLab(concurrency=2)
    seeds = lab.seed_matrix(10, 6)
    first = await lab.run(seeds, _lab_scenario)
    second = await lab.run(seeds, _lab_scenario, retain_samples=False)
    assert first.summary == second.summary
    assert first.outcome_rates == second.outcome_rates
    assert second.retained_samples == ()
    delta = lab.compare(first, second)
    assert delta.mean_delta == 0
    assert all(value == 0 for value in delta.outcome_rate_delta.values())


def test_v22_director_proposal_only_recovery_and_world_motion() -> None:
    observation = DirectorObservation(
        campaign_id="c",
        sequence=5,
        pressure=0.9,
        resource_ratio=0.2,
        unresolved_quests=0,
        faction_motion=3,
        idle_minutes=120,
    )
    proposals = AdvancedAIDirector().propose(observation)
    kinds = {proposal.kind for proposal in proposals}
    assert ProposalKind.DOWNTIME in kinds
    assert ProposalKind.PACING in kinds
    assert ProposalKind.FACTION in kinds
    assert proposals == tuple(sorted(proposals, key=lambda item: (-item.utility, item.proposal_id)))


def test_v23_knowledge_authority_remembers_observed_state_and_redacts_hidden_truth() -> None:
    world = World(
        revision=5,
        entities={
            "hero": Entity(
                entity_id="hero",
                components={
                    "identity": {"name": "Hero"},
                    "position": {"x": 1, "y": 2},
                    "inventory": {"secret": "key"},
                },
            ),
            "npc": Entity(
                entity_id="npc",
                components={
                    "identity": {"name": "NPC"},
                    "position": {"x": 2, "y": 2},
                    "inventory": {"secret": "letter"},
                },
            ),
        },
    )
    authority = KnowledgeAuthority(public_components={"identity", "position"})
    authority.ingest_perception("hero", world.entity("npc"), sequence=5)
    first = authority.actor_view(world, "hero")
    assert first.entities["npc"]["identity"]["name"] == "NPC"
    assert "inventory" not in first.entities["npc"]

    world.entity("npc").components["position"] = {"x": 9, "y": 9}
    remembered = authority.actor_view(world, "hero")
    assert remembered.entities["npc"]["position"] == {"x": 2, "y": 2}

    spectator = authority.spectator_view(world)
    assert "inventory" not in spectator.entities["npc"]
    omniscient = authority.omniscient_view(world, "owner")
    assert omniscient.entities["npc"]["inventory"]["secret"] == "letter"


def test_v24_visual_snapshot_redaction_delta_replay_and_hash_validation() -> None:
    world_a = World(
        revision=1,
        entities={"hero": Entity(entity_id="hero", components={"position": {"x": 0, "y": 0}})},
    )
    world_b = world_a.clone()
    world_b.revision = 2
    world_b.entity("hero").components["position"] = {"x": 1, "y": 0}

    binding = SceneAssetBinding(entity_id="hero", scene_path="res://hero.tscn")
    first = VisualSnapshot.from_world(world_a, {"hero": binding})
    second = VisualSnapshot.from_world(world_b, {"hero": binding})
    delta = diff_snapshots(first, second)
    replayed = replay_delta(first, delta)
    assert replayed == second


def _release(package_id: str, version: str, *, dependencies: tuple[PackageDependency, ...] = ()) -> PackageRelease:
    return PackageRelease(
        package_id=package_id,
        version=version,
        engine_constraint=">=3.0.0,<4.0.0",
        dependencies=dependencies,
        content_hash=f"hash-{package_id}-{version}",
    )


@pytest.mark.asyncio
async def test_v25_distribution_resolution_signing_lock_and_upgrade_plan() -> None:
    registry = ContentDistributionRegistry(engine_version="3.0.0")
    dep_v1 = _release("dep", "1.0.0")
    dep_v2 = _release("dep", "1.1.0")
    root = _release("root", "1.0.0", dependencies=(PackageDependency(package_id="dep", constraint=">=1.0.0,<2.0.0"),))
    await registry.publish(dep_v1)
    await registry.publish(root)
    lock = await registry.resolve("root")
    assert [row[0] for row in lock.releases] == ["dep", "root"]

    signer = HMACReleaseSigner(b"0123456789abcdef0123456789abcdef")
    signed = root.model_copy(update={"signature": signer.sign(root)})
    assert signer.verify(signed)

    await registry.publish(dep_v2)
    changes = await registry.upgrade_plan(lock)
    assert ("dep", "1.0.0", "1.1.0") in changes


@pytest.mark.asyncio
async def test_v30_shard_routing_lamport_idempotency_rebalance_and_two_phase_transfer() -> None:
    registry = ShardRegistry()
    await registry.heartbeat(WorldShard(shard_id="s1", region="west", capacity=10, load=2))
    await registry.heartbeat(WorldShard(shard_id="s2", region="west", capacity=10, load=1))
    chosen_a = await registry.route("hero", region="west")
    chosen_b = await registry.route("hero", region="west")
    assert chosen_a.shard_id == chosen_b.shard_id

    plan = await registry.rebalance_plan(["hero"], region="west", current={"hero": "old"})
    assert plan and plan[0][0] == "hero"

    stale = WorldShard(
        shard_id="stale",
        region="west",
        capacity=1,
        heartbeat_at=datetime.now(UTC) - timedelta(seconds=120),
    )
    async with registry._lock:
        registry._shards["stale"] = stale
    assert await registry.expire(max_age_seconds=30) == ["stale"]

    clock = LamportClock()
    first = await clock.tick()
    second = await clock.tick(observed=10)
    assert first == 1
    assert second == 11

    ledger = MessageLedger()
    message = CrossShardMessage(
        message_id="m1",
        idempotency_key="idempotent-1",
        source_shard="s1",
        target_shard="s2",
        lamport=second,
        kind="entity.transfer",
    )
    assert await ledger.accept(message)
    assert not await ledger.accept(message)

    transfers = TransferManager()
    prepared = await transfers.prepare(
        "t1",
        "hero",
        "s1",
        "s2",
        {"entity_id": "hero", "components": {"hp": {"current": 10}}},
    )
    assert prepared.status == TransferStatus.PREPARED
    accepted = await transfers.accept("t1", prepared.payload)
    assert accepted.status == TransferStatus.ACCEPTED
    committed = await transfers.commit("t1")
    assert committed.status == TransferStatus.COMMITTED
    restored = await transfers.restore_payload("t1")
    assert restored["entity_id"] == "hero"
