import pytest

from rpg_engine_dnd.adventure import (
    DialogueChoice,
    DialogueGraph,
    DialogueNode,
    GraphMap,
    MapEdge,
    MapNode,
    Quest,
    QuestObjective,
    Shop,
    ShopStock,
)
from rpg_engine_dnd.ai import BoundedMemory, ProceduralDirector
from rpg_engine_dnd.combat import CombatSystem, Combatant, Condition, Item, Position
from rpg_engine_dnd.creator import CampaignTemplate, ContentValidator, ModManifest, ModPackage
from rpg_engine_dnd.living_world import (
    DynamicEventEngine,
    DynamicEventRule,
    Economy,
    MarketItem,
    NPCSchedule,
    ScheduleEntry,
    WeatherState,
    WeatherSystem,
    WeatherTransition,
    WorldClock,
)
from rpg_engine_dnd.multiplayer import CampaignSession, Participant
from rpg_engine_dnd.platform import CampaignFactory, CommunityContentRegistry, MarketplaceEntry
from rpg_engine_dnd.visual import GodotBridge, SceneAssetBinding


def test_v02_combat_timeline_movement_conditions_inventory() -> None:
    combat = CombatSystem(seed=42)
    combat.register(
        Combatant(
            actor_id="hero",
            armor_class=15,
            hit_points=20,
            max_hit_points=20,
            speed=5,
            position=Position(x=0, y=0),
        )
    )
    combat.register(
        Combatant(
            actor_id="goblin",
            armor_class=10,
            hit_points=9,
            max_hit_points=9,
            speed=5,
            position=Position(x=3, y=0),
        )
    )

    order = combat.start()
    assert sorted(order) == ["goblin", "hero"]

    path = combat.move("hero", Position(x=2, y=0))
    assert path[0] == Position(x=0, y=0)
    assert path[-1] == Position(x=2, y=0)
    assert combat.line_of_sight(Position(x=0, y=0), Position(x=3, y=0))
    assert not combat.line_of_sight(
        Position(x=0, y=0),
        Position(x=3, y=0),
        blocked=[Position(x=1, y=0)],
    )

    combat.add_condition("goblin", Condition(name="burning", rounds_remaining=2, periodic_damage=1))
    action = combat.schedule("hero", "spell.resolve", delay_ticks=2, payload={"spell_id": "spark"})
    assert combat.advance(1) == []
    assert combat.combatants["goblin"].hit_points == 8
    assert combat.advance(1) == [action]
    assert combat.combatants["goblin"].hit_points == 7
    assert combat.conditions["goblin"] == []

    inventory = combat.inventories["hero"]
    inventory.add(Item(item_id="ration", name="Ration", quantity=2))
    inventory.add(Item(item_id="ration", name="Ration", quantity=3))
    assert inventory.items["ration"].quantity == 5
    removed = inventory.remove("ration", 2)
    assert removed.quantity == 2
    assert inventory.items["ration"].quantity == 3


def test_v03_adventure_graph_dialogue_quests_and_shop() -> None:
    graph = GraphMap()
    graph.add_node(MapNode(node_id="village", name="Village", discoveries=("well",)))
    graph.add_node(MapNode(node_id="forest", name="Forest", discoveries=("ruins",)))
    graph.add_edge(MapEdge(source="village", target="forest", cost=2.0))
    assert graph.neighbors("village") == [("forest", 2.0)]
    assert graph.explore("hero", "forest") == ("ruins",)
    assert graph.explore("hero", "forest") == ()

    dialogue = DialogueGraph(
        start_node="start",
        nodes={
            "start": DialogueNode(
                node_id="start",
                speaker="npc",
                text="Hello",
                choices=(
                    DialogueChoice(text="Ask", requires={"knows_secret": True}),
                    DialogueChoice(text="Leave"),
                ),
            )
        },
    )
    assert [choice.text for choice in dialogue.available_choices("start", {})] == ["Leave"]
    assert [choice.text for choice in dialogue.available_choices("start", {"knows_secret": True})] == ["Ask", "Leave"]

    quest = Quest(
        quest_id="q1",
        title="Explore",
        objectives=[QuestObjective(objective_id="o1", event_kind="ruins.discovered", target=2)],
    )
    assert not quest.ingest_event("ruins.discovered")
    assert quest.ingest_event("ruins.discovered")

    shop = Shop(shop_id="general", stock={"ration": ShopStock(item_id="ration", price=3, quantity=4)})
    assert shop.buy("ration", quantity=2) == 6
    assert shop.stock["ration"].quantity == 2
    assert shop.sell_to_shop("rope", unit_price=5, quantity=2) == 10
    assert shop.stock["rope"].quantity == 2


def test_v04_living_world_clock_weather_schedule_economy_events() -> None:
    clock = WorldClock()
    assert clock.advance(1500) == 1500
    assert clock.day == 1
    assert clock.minute_of_day == 60

    weather = WeatherSystem(
        seed="weather-seed",
        states=[
            WeatherState(name="clear", temperature_c=20),
            WeatherState(name="rain", temperature_c=14, visibility=0.7),
        ],
        transitions=[
            WeatherTransition(source="clear", target="rain", weight=1),
            WeatherTransition(source="clear", target="clear", weight=1),
        ],
    )
    first = weather.next("clear")
    replay = WeatherSystem(
        seed="weather-seed",
        states=[
            WeatherState(name="clear", temperature_c=20),
            WeatherState(name="rain", temperature_c=14, visibility=0.7),
        ],
        transitions=[
            WeatherTransition(source="clear", target="rain", weight=1),
            WeatherTransition(source="clear", target="clear", weight=1),
        ],
    ).next("clear")
    assert first == replay

    schedule = NPCSchedule(
        entries=[ScheduleEntry(start_minute=0, end_minute=480, location_id="home", activity="sleep")]
    )
    assert schedule.current(120) is not None
    assert schedule.current(900) is None

    economy = Economy(items={"grain": MarketItem(item_id="grain", base_price=10, supply=5, demand=5)})
    initial_price = economy.items["grain"].price
    paid = economy.transact("grain", 2)
    assert paid == initial_price * 2
    assert economy.items["grain"].supply == 3

    dynamic = DynamicEventEngine(
        rules=[DynamicEventRule(event_id="storm", requires={"weather": "rain"}, emits="road.flooded")]
    )
    assert dynamic.evaluate({"weather": "clear"}) == []
    assert dynamic.evaluate({"weather": "rain"}) == ["road.flooded"]
    assert dynamic.evaluate({"weather": "rain"}) == []


@pytest.mark.asyncio
async def test_v07_v08_ai_memory_multiplayer_and_hosting_boundaries() -> None:
    memory = BoundedMemory(max_items=2)
    memory.add("a")
    memory.add("b")
    memory.add("c")
    assert memory.context() == ("b", "c")

    director_a = ProceduralDirector(seed=17)
    director_b = ProceduralDirector(seed=17)
    assert director_a.encounter(index=1, creature_pool=("a", "b", "c"), budget=3) == director_b.encounter(
        index=1,
        creature_pool=("a", "b", "c"),
        budget=3,
    )

    session = CampaignSession("campaign")
    await session.join(Participant(user_id="player"))
    await session.join(Participant(user_id="spectator", spectator=True))
    await session.assign_actor("player", "hero")
    await session.require_actor_control("player", "hero")
    with pytest.raises(PermissionError):
        await session.assign_actor("spectator", "npc")


@pytest.mark.asyncio
async def test_v09_v10_creator_package_registry_and_campaign_instantiation() -> None:
    template = CampaignTemplate(
        template_id="starter",
        name="Starter",
        starting_scene="village",
        entities=[{"entity_id": "hero", "components": {"identity": {"name": "Hero"}}}],
    )
    assert ContentValidator().validate_template(template) == []
    world = CampaignFactory.instantiate(template)
    assert world.entity("hero").components["identity"]["name"] == "Hero"

    manifest = ModManifest(package_id="starter", version="1.0.0")
    package_bytes = await ModPackage.build(manifest, {"campaign.json": b"{}"})
    inspected_manifest, files = await ModPackage.inspect(package_bytes)
    assert inspected_manifest.package_id == "starter"
    assert files == {"campaign.json": b"{}"}

    registry = CommunityContentRegistry()
    entry = MarketplaceEntry(
        package_id="starter",
        version="1.0.0",
        title="Starter",
        author="test",
        content_hash="abc",
    )
    await registry.publish(entry)
    assert await registry.get("starter", "1.0.0") == entry

    bridge = GodotBridge([SceneAssetBinding(entity_id="hero", scene_path="res://hero.tscn")])
    projection = bridge.project(world)
    assert projection[0].binding is not None
    assert projection[0].binding.scene_path == "res://hero.tscn"
