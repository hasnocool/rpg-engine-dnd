import pytest

from rpg_engine_dnd.actors import (
    ActorGoal,
    ActorMemory,
    ConditionNode,
    LivingActor,
    PerceivedEntity,
    PerceptionSnapshot,
    SequenceNode,
    TacticalPlanner,
    UtilityAI,
    UtilityOption,
)
from rpg_engine_dnd.compiler import RuleCompiler, RuleDocument, RuleInterpreter, RuleNode
from rpg_engine_dnd.event_sourcing import EventJournal, apply_patch, make_patch
from rpg_engine_dnd.lifecycle import (
    CharacterBuild,
    CharacterLifecycle,
    EquipmentItem,
    ProgressionState,
    ProgressionTrack,
    ResourcePool,
)
from rpg_engine_dnd.rules import AttackContext, DamageContext, Effect, RulesRuntime
from rpg_engine_dnd.spatial import ContinuousSpace, GraphSpace, GridCell, GridSpace
from rpg_engine_dnd.srd import (
    AdvantageState,
    DamageTrait,
    HitPointState,
    SRDCatalogs,
    apply_damage_trait,
    proficiency_bonus,
)


def test_v11_srd_structures_and_mechanics() -> None:
    catalogs = SRDCatalogs.structural_defaults()
    assert "acrobatics" in catalogs.skills
    assert "fighter" in catalogs.classes
    assert proficiency_bonus(1) == 2
    assert proficiency_bonus(5) == 3
    assert apply_damage_trait(9, DamageTrait.RESISTANCE) == 4
    assert apply_damage_trait(9, DamageTrait.VULNERABILITY) == 18

    hp = HitPointState(current=10, maximum=10, temporary=3)
    assert hp.damage(5) == 2
    assert hp.temporary == 0
    assert hp.current == 8
    hp.current = 0
    assert hp.record_death_save(True) == "pending"
    assert hp.record_death_save(True) == "pending"
    assert hp.record_death_save(True) == "stable"


def test_v12_rules_runtime_roll_attack_damage_effects_and_action_economy() -> None:
    runtime = RulesRuntime(seed=99)
    attack = runtime.attack(
        AttackContext(
            attacker_id="hero",
            target_id="target",
            armor_class=10,
            attack_bonus=5,
            advantage=AdvantageState.ADVANTAGE,
        )
    )
    assert len(attack.roll.raw_rolls) == 2
    assert attack.roll.total == attack.roll.selected + 5

    damage = runtime.damage(
        DamageContext(source_id="hero", target_id="target", expression="2d6", damage_type="fire")
    )
    assert damage.amount >= 2
    assert damage.damage_type == "fire"

    runtime.register_hook(
        "burn",
        lambda effect: [
            Effect(
                effect_id=f"{effect.effect_id}:child",
                source_id=effect.source_id,
                target_id=effect.target_id,
                kind="smoke",
            )
        ],
    )
    effects = runtime.apply_effect(Effect(effect_id="e1", source_id="hero", target_id="target", kind="burn"))
    assert [effect.kind for effect in effects] == ["burn", "smoke"]

    economy = runtime.reset_turn("hero", movement=30)
    economy.spend("action")
    economy.spend("movement", 10)
    assert economy.action == 0
    assert economy.movement == 20


def test_v13_event_journal_replay_rewind_branch_hashes_and_idempotency() -> None:
    initial = {"entities": {"hero": {"hp": 10}}}
    second = {"entities": {"hero": {"hp": 7}}}
    third = {"entities": {"hero": {"hp": 7, "position": [1, 2]}}}
    journal = EventJournal(initial)

    one = journal.append(command_id="c1", event_kind="damage", before=initial, after=second)
    duplicate = journal.append(command_id="c1", event_kind="damage", before=initial, after=second)
    assert duplicate == one
    journal.append(command_id="c2", event_kind="move", before=second, after=third)

    assert journal.replay() == third
    assert journal.rewind(1) == second
    assert journal.branch(1).replay() == second
    assert journal.verify_live_state(third)

    patch = make_patch(initial, third)
    assert apply_patch(initial, patch) == third


def test_v14_spatial_graph_grid_continuous_authority() -> None:
    graph = GraphSpace(capacities={"a": 1, "b": 2})
    graph.connect("a", "b", cost=2.0)
    assert graph.route("a", "b") == ["a", "b"]
    graph.enter("a", "hero")
    with pytest.raises(ValueError):
        graph.enter("a", "npc")

    grid = GridSpace(
        width=4,
        height=4,
        cells={
            (1, 1): GridCell(x=1, y=1, blocks_movement=True, blocks_los=True),
            (2, 0): GridCell(x=2, y=0, terrain="mud", movement_cost=2.0, cover=1),
        },
    )
    route = grid.path((0, 0), (3, 0), budget=5.0)
    assert route[0] == (0, 0)
    assert route[-1] == (3, 0)
    assert not grid.line_of_sight((0, 1), (3, 1))
    assert grid.cover((0, 0), (3, 0)) == 1

    continuous = ContinuousSpace(dimensions=2, minimum=(0.0, 0.0), maximum=(10.0, 10.0))
    continuous.radii = {"hero": 0.5, "npc": 0.5}
    continuous.move("hero", (1.0, 1.0))
    continuous.move("npc", (4.0, 4.0))
    continuous.move("hero", (2.0, 2.0), movement_budget=2.0)
    with pytest.raises(ValueError):
        continuous.move("hero", (4.0, 4.0), movement_budget=10.0)


def test_v15_actor_perception_utility_behavior_planning_memory_schedule() -> None:
    snapshot = PerceptionSnapshot(
        actor_id="npc",
        sequence=1,
        entities=(PerceivedEntity(entity_id="hero", distance=3.0, tags=frozenset({"hostile"})),),
    )
    goals = [ActorGoal(goal_id="survive", priority=2.0, tags={"safety"})]
    option = UtilityAI().choose(
        [
            UtilityOption(action="wait", base_score=0.1),
            UtilityOption(action="approach", base_score=0.5, requires_tags=frozenset({"hostile"}), goal_tags=frozenset({"safety"})),
        ],
        snapshot,
        goals,
    )
    assert option.action == "approach"

    facts = {"alert": True}
    tree = SequenceNode((ConditionNode("alert", True),))
    assert tree.tick(facts).value == "success"

    command = TacticalPlanner().plan("npc", snapshot, "approach")
    assert command.payload["target_id"] == "hero"

    actor = LivingActor(actor_id="npc", schedule_intents={0: "sleep", 480: "work"})
    actor.remember(ActorMemory(sequence=1, subject_id="hero", fact="seen"))
    assert actor.scheduled_intent(600) == "work"
    assert actor.memories[-1].fact == "seen"


def test_v16_character_lifecycle_progression_resources_equipment() -> None:
    lifecycle = CharacterLifecycle(
        build=CharacterBuild(character_id="hero", name="Hero", class_levels={"fighter": 1}),
        progression=ProgressionState(level=1),
        resources={
            "focus": ResourcePool(
                resource_id="focus",
                current=1,
                maximum=3,
                recover_short=1,
                recover_long=3,
            )
        },
    )
    lifecycle.build.add_class_level("wizard")
    assert lifecycle.build.level == 2

    track = ProgressionTrack({1: 0, 2: 100, 3: 300})
    assert track.add_xp(lifecycle.progression, 150) == 2
    outcome = track.advance(
        lifecycle.progression,
        to_level=2,
        hit_point_gain=6,
        features=("feature-a",),
        ability_points=1,
    )
    assert outcome.new_level == 2
    assert "feature-a" in lifecycle.progression.features

    lifecycle.resources["focus"].spend()
    lifecycle.rest("short")
    assert lifecycle.resources["focus"].current == 1

    item = EquipmentItem(
        item_id="ring",
        slot="ring",
        attunement_required=True,
        modifiers={"armor": 1},
    )
    lifecycle.equipment.equip(item)
    lifecycle.equipment.attune(item)
    assert lifecycle.equipment.aggregate_modifiers() == {"armor": 1}


def test_v19_compiler_bounded_graph_hash_execution_and_state_allowlist() -> None:
    document = RuleDocument(
        rule_id="test-rule",
        entry_point="roll",
        allowed_state_paths=frozenset({"flags.success"}),
        nodes={
            "roll": RuleNode(
                node_id="roll",
                op="roll",
                args={"actor_id": "hero", "bonus": 100, "threshold": 10},
                true_node="state",
                false_node="stop",
            ),
            "state": RuleNode(
                node_id="state",
                op="state",
                args={"path": "flags.success", "value": True},
                next_node="emit",
            ),
            "emit": RuleNode(
                node_id="emit",
                op="emit",
                args={"event": "rule.success"},
                next_node="stop",
            ),
            "stop": RuleNode(node_id="stop", op="stop"),
        },
    )
    compiled = RuleCompiler(max_nodes=10).compile(document)
    result = RuleInterpreter(RulesRuntime(seed=1)).execute(compiled)
    assert result.state == {"flags": {"success": True}}
    assert result.emitted == ("rule.success",)
    assert result.graph_hash == compiled.graph_hash

    invalid = document.model_copy(
        update={
            "nodes": {
                **document.nodes,
                "bad": RuleNode(node_id="bad", op="state", args={"path": "private.secret", "value": 1}),
            }
        }
    )
    with pytest.raises(ValueError):
        RuleCompiler().compile(invalid)
