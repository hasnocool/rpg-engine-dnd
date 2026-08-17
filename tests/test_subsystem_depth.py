"""Regression coverage for v3.0.1-v3.3.0 subsystem-depth upgrades."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from rpg_engine_dnd.balancing import BalanceLab, BalanceSample, DirectorCandidate, PredictiveDirector
from rpg_engine_dnd.commands import CreateEntity
from rpg_engine_dnd.compiler_vm import IRInstruction, IROp, RuleIRCompiler
from rpg_engine_dnd.content_security import (
    ContentAttestation,
    PackageCapabilityManifest,
    PublisherIdentity,
    TrustPolicy,
)
from rpg_engine_dnd.distributed_runtime import DurableMessage, DurableShardCoordinator
from rpg_engine_dnd.hosting_ops import BackpressureGate, LeaseFence
from rpg_engine_dnd.intelligence_v2 import GOAPAction, GOAPPlanner
from rpg_engine_dnd.knowledge_graph import KnowledgeGraph, KnownFact, Visibility
from rpg_engine_dnd.lifecycle_features import ResourcePool
from rpg_engine_dnd.mechanics import Modifier, ModifierOperation, ModifierResolver, ReactionChoice, ReactionStack, ReactionWindow
from rpg_engine_dnd.orchestrator import Scene, SceneStatus, SceneType
from rpg_engine_dnd.orchestration_tree import NodeState, SceneNode, SceneTree
from rpg_engine_dnd.persistence import AsyncSQLitePlatformStore
from rpg_engine_dnd.protocol import AreaOfInterest, CommandEnvelope, InterestEntity, InterestManager, validate_expected_revision
from rpg_engine_dnd.scheduler import ScheduleDomain, SimulationScheduler
from rpg_engine_dnd.semantic_events import SemanticEventJournal
from rpg_engine_dnd.spatial_query import HexCell, HexGridSpace, SpatialQueryService
from rpg_engine_dnd.world_depth import (
    ClimateProfile,
    FactionGraph,
    FactionRelation,
    ObjectiveNode,
    ObjectiveStatus,
    QuestGraph,
    SettlementMarket,
    WeatherFront,
    WeatherRegion,
)
from rpg_engine_dnd.world_platform import WorldPlatformEngine


def test_scheduler_orders_domains_and_cancellation() -> None:
    scheduler = SimulationScheduler()
    scheduler.schedule("weather", delay_ticks=10, domain=ScheduleDomain.WEATHER, kind="weather.advance")
    scheduler.schedule("spell", delay_ticks=2, domain=ScheduleDomain.SPELL, kind="spell.complete")
    scheduler.schedule("cancelled", delay_ticks=1, domain=ScheduleDomain.AI, kind="actor.think")
    assert scheduler.cancel("cancelled")
    assert scheduler.advance(2)[0].task_id == "spell"
    assert scheduler.advance(8)[0].task_id == "weather"


def test_modifier_algebra_and_reaction_stack() -> None:
    resolver = ModifierResolver()
    resolution = resolver.resolve(
        10,
        [
            Modifier(modifier_id="a", source="feat", target="hero", scope="attack", operation=ModifierOperation.ADD, value=2),
            Modifier(modifier_id="b", source="spell", target="hero", scope="attack", operation=ModifierOperation.MULTIPLY, value=2),
        ],
    )
    assert resolution.value == 24

    stack = ReactionStack()
    window = ReactionWindow(window_id="w", trigger="attacked", opened_sequence=1, eligible_actors=frozenset({"hero"}))
    stack.open(window)
    window.offer(ReactionChoice(reaction_id="shield", actor_id="hero", action_kind="shield", priority=5))
    assert stack.resolve_current()[0].reaction_id == "shield"


def test_semantic_journal_snapshots_and_segments() -> None:
    journal = SemanticEventJournal({"value": 0}, snapshot_interval=1)
    journal.append(command_id="c1", event_kind="value.changed", before={"value": 0}, after={"value": 1})
    assert journal.verify()
    assert journal.snapshots[-1].state == {"value": 1}
    assert journal.segments(size=1)[0].start_sequence == 1


def test_optimistic_concurrency_and_interest_management() -> None:
    envelope = CommandEnvelope(command_id="c", kind="move", expected_world_revision=3)
    validate_expected_revision(envelope, 3)
    with pytest.raises(ValueError):
        validate_expected_revision(envelope, 4)

    selected = InterestManager().select(
        AreaOfInterest(center=(0.0, 0.0), radius=5.0),
        [InterestEntity(entity_id="near", position=(2.0, 0.0)), InterestEntity(entity_id="far", position=(20.0, 0.0))],
    )
    assert [item.entity_id for item in selected] == ["near"]


def test_goap_builds_multi_step_plan() -> None:
    plan = GOAPPlanner().plan(
        {"money": False, "food": False},
        {"food": True},
        [
            GOAPAction(action_id="work", preconditions={"money": False}, effects={"money": True}),
            GOAPAction(action_id="buy", preconditions={"money": True}, effects={"food": True}),
        ],
    )
    assert plan.actions == ("work", "buy")


def test_quest_economy_faction_and_weather_depth() -> None:
    quest = QuestGraph(
        quest_id="q",
        objectives={
            "find": ObjectiveNode(objective_id="find", status=ObjectiveStatus.ACTIVE, event_kind="item.found"),
            "return": ObjectiveNode(objective_id="return", requires=frozenset({"find"}), event_kind="npc.returned"),
        },
    )
    assert quest.ingest_event("item.found") == ("find",)
    assert quest.objectives["return"].status == ObjectiveStatus.ACTIVE
    assert quest.ingest_event("npc.returned") == ("return",)

    market = SettlementMarket(settlement_id="town", inventory={"grain": 5}, base_prices={"grain": 10})
    assert market.price("grain") > 10

    factions = FactionGraph()
    factions.set_relation("a", "b", FactionRelation.ALLIED)
    assert factions.relation("b", "a") == FactionRelation.ALLIED

    region = WeatherRegion(
        region_id="coast",
        climate=ClimateProfile(climate_id="temperate", base_temperature_c=12),
        season_phase=0.5,
        active_front=WeatherFront(front_id="warm", temperature_delta_c=3),
    )
    assert region.temperature_c == 15


def test_hex_spatial_authority() -> None:
    space = HexGridSpace()
    path = SpatialQueryService().path(space, (0, 0), (2, -1))
    assert path[0] == (0, 0)
    assert path[-1] == (2, -1)


def test_hex_spatial_authority_prefers_longer_low_cost_route() -> None:
    space = HexGridSpace(
        cells={
            (1, 0): HexCell(q=1, r=0, movement_cost=2.0),
            (0, 1): HexCell(q=0, r=1, movement_cost=0.1),
            (1, 1): HexCell(q=1, r=1, movement_cost=0.1),
            (2, 0): HexCell(q=2, r=0, movement_cost=0.1),
        }
    )
    path = space.path((0, 0), (2, 0))
    assert path == [(0, 0), (0, 1), (1, 1), (2, 0)]


def test_lifecycle_resource_and_compiler_ir() -> None:
    resource = ResourcePool(resource_id="focus", current=2, maximum=3, short_rest_recovery=1)
    resource.spend()
    resource.recover()
    assert resource.current == 2

    plan = RuleIRCompiler().compile(
        "a",
        [
            IRInstruction(instruction_id="a", op=IROp.CONST, next_ids=("b",)),
            IRInstruction(instruction_id="b", op=IROp.STOP),
            IRInstruction(instruction_id="dead", op=IROp.STOP),
        ],
    )
    assert [item.instruction_id for item in plan.instructions] == ["a", "b"]


def test_scene_tree_allows_active_hierarchy() -> None:
    tree = SceneTree()
    tree.add(SceneNode(scene_id="world", state=NodeState.ACTIVE, entity_ids={"global"}))
    tree.add(SceneNode(scene_id="dungeon", parent_id="world", entity_ids={"orc"}))
    tree.set_state("dungeon", NodeState.ACTIVE)
    assert tree.streamed_entities() == {"global", "orc"}


def test_balancing_predictive_director_and_knowledge() -> None:
    report = BalanceLab().summarize([
        BalanceSample(outcome="success", rounds=3),
        BalanceSample(outcome="success", rounds=5),
    ])
    ranked = PredictiveDirector().rank([
        DirectorCandidate(candidate_id="safe", pacing_score=1, risk=0.1, resource_pressure=0.1, report=report),
        DirectorCandidate(candidate_id="risky", pacing_score=1, risk=0.8, resource_pressure=0.4, report=report),
    ])
    assert ranked[0].candidate_id == "safe"

    graph = KnowledgeGraph()
    graph.add(KnownFact(
        fact_id="f", subject="dragon", predicate="location", value="cave", source="scout",
        observed_at=10, visibility=Visibility.PARTY,
    ))
    assert graph.query("dragon", sequence=11)[0].value == "cave"


def test_content_trust_requires_valid_signature_when_enabled() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    identity = PublisherIdentity(
        publisher_id="p",
        public_key_b64=base64.b64encode(public_key).decode("ascii"),
    )
    unsigned = ContentAttestation(
        package_id="pkg",
        package_version="1.0",
        content_hash="abc",
        publisher_id="p",
        capabilities=PackageCapabilityManifest(requested=frozenset({"rules"})),
        signature_b64="",
    )
    signature = private_key.sign(unsigned.signed_material())
    attestation = unsigned.model_copy(
        update={"signature_b64": base64.b64encode(signature).decode("ascii")}
    )
    policy = TrustPolicy(trusted_publishers=frozenset({"p"}))
    policy.enforce(attestation, identity=identity)

    with pytest.raises(ValueError, match="identity is required"):
        policy.enforce(attestation)
    with pytest.raises(ValueError, match="signature verification failed"):
        policy.enforce(attestation.model_copy(update={"signature_b64": "AA=="}), identity=identity)
    with pytest.raises(ValueError):
        TrustPolicy(
            denied_capabilities=frozenset({"rules"}),
            require_signature=False,
        ).enforce(attestation)


def test_content_trust_and_hosting_fence() -> None:
    attestation = ContentAttestation(
        package_id="pkg", package_version="1.0", content_hash="abc", publisher_id="p",
        capabilities=PackageCapabilityManifest(requested=frozenset({"rules"})), signature_b64="AA==",
    )
    TrustPolicy(trusted_publishers=frozenset({"p"}), require_signature=False).enforce(attestation)

    older = LeaseFence(lease_id="l1", worker_id="w", generation=1, fencing_token=1)
    newer = LeaseFence(lease_id="l2", worker_id="w", generation=2, fencing_token=2)
    newer.assert_newer_than(older)
    gate = BackpressureGate(capacity=1)
    gate.acquire()
    with pytest.raises(RuntimeError):
        gate.acquire()
    gate.release()


def test_world_platform_journals_core_commands_atomically() -> None:
    engine = WorldPlatformEngine(seed=7)
    event = engine.handle(CreateEntity(command_id="c1", entity_id="hero", components={"identity": {"name": "Hero"}}))
    assert event.kind == "entity.created"
    assert engine.semantic_journal.verify()
    assert engine.snapshot()["journal_head_hash"] == engine.semantic_journal.journal.head_hash


def test_world_platform_deduplicates_before_mutation_and_rejects_conflicts() -> None:
    engine = WorldPlatformEngine(seed=7)
    command = CreateEntity(command_id="same", entity_id="hero", components={})
    first = engine.handle(command)
    second = engine.handle(command)

    assert second == first
    assert engine.world.revision == 1
    assert len(engine.semantic_journal.journal.entries) == 1
    assert engine.semantic_journal.verify()

    with pytest.raises(ValueError, match="reused for a different command"):
        engine.handle(CreateEntity(command_id="same", entity_id="other", components={}))
    assert engine.world.revision == 1
    assert "other" not in engine.world.entities


def test_scene_mutations_do_not_break_command_journal_replay() -> None:
    engine = WorldPlatformEngine(seed=7)
    engine.orchestrator.register(Scene(scene_id="town", scene_type=SceneType.SETTLEMENT))
    engine.orchestrator.transition("town", SceneStatus.LOADING)
    engine.orchestrator.transition("town", SceneStatus.ACTIVE)

    event = engine.handle(CreateEntity(command_id="after-scene", entity_id="hero", components={}))
    assert event.kind == "entity.created"
    assert engine.semantic_journal.verify()
    assert engine.snapshot()["orchestrator"]["active_scene_id"] == "town"


class _FakeStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], dict[str, object]] = {}

    async def get_json(self, namespace: str, key: str) -> dict[str, object] | None:
        return self.values.get((namespace, key))

    async def put_json(self, namespace: str, key: str, value: dict[str, object]) -> None:
        self.values[(namespace, key)] = value


class _FailOnceCASStore(_FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.failed_message_write = False

    async def put_json(self, namespace: str, key: str, value: dict[str, object]) -> None:
        if namespace == "world:message" and not self.failed_message_write:
            self.failed_message_write = True
            raise OSError("transient message write failure")
        await super().put_json(namespace, key, value)

    async def compare_and_set_json(
        self,
        namespace: str,
        key: str,
        expected: dict[str, object] | None,
        value: dict[str, object],
    ) -> bool:
        current = self.values.get((namespace, key))
        if current != expected:
            return False
        self.values[(namespace, key)] = value
        return True


@pytest.mark.asyncio
async def test_durable_shard_fencing_and_idempotency() -> None:
    coordinator = DurableShardCoordinator(_FakeStore())
    first = await coordinator.acquire_lease(shard_id="s", region="r", owner_id="w1", lease_id="l1")
    second = await coordinator.acquire_lease(shard_id="s", region="r", owner_id="w2", lease_id="l2")
    assert second.epoch == first.epoch + 1
    with pytest.raises(ValueError):
        await coordinator.assert_fence("s", first.fencing_token)
    await coordinator.assert_fence("s", second.fencing_token)

    message = DurableMessage(
        message_id="m", idempotency_key="i", source_shard="a", target_shard="b", sequence=1, kind="entity.transfer"
    )
    assert await coordinator.publish(message)
    assert not await coordinator.publish(message)


@pytest.mark.asyncio
async def test_durable_publish_recovers_pending_cas_claim_after_io_failure() -> None:
    store = _FailOnceCASStore()
    coordinator = DurableShardCoordinator(store)
    message = DurableMessage(
        message_id="recover",
        idempotency_key="recover-key",
        source_shard="a",
        target_shard="b",
        sequence=1,
        kind="entity.transfer",
    )

    with pytest.raises(OSError, match="transient"):
        await coordinator.publish(message)
    claim = await store.get_json("world:message-idempotency", "recover-key")
    assert claim is not None and claim["status"] == "pending"
    assert await store.get_json("world:message", "recover") is None

    assert await coordinator.publish(message)
    assert not await coordinator.publish(message)
    assert await store.get_json("world:message", "recover") == message.model_dump(mode="json")
    final = await store.get_json("world:message-idempotency", "recover-key")
    assert final is not None and final["status"] == "complete"


@pytest.mark.asyncio
async def test_sqlite_compare_and_set_is_atomic(tmp_path: Path) -> None:
    store = AsyncSQLitePlatformStore(tmp_path / "cas.sqlite")
    await store.initialize()

    async def claim(value: int) -> bool:
        return await store.compare_and_set_json("claims", "one", None, {"value": value})

    results = await asyncio.gather(claim(1), claim(2))
    assert sum(results) == 1
    current = await store.get_json("claims", "one")
    assert current in ({"value": 1}, {"value": 2})
    assert current is not None
    assert await store.compare_and_set_json("claims", "one", current, {"value": 3})
    assert await store.get_json("claims", "one") == {"value": 3}
