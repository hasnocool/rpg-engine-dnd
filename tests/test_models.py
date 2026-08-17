from rpg_engine_dnd import AbilityScores, Entity, World


def test_world_clone_is_independent() -> None:
    world = World(entities={"hero": Entity(entity_id="hero", components={"hp": {"current": 10}})})
    clone = world.clone()
    clone.entities["hero"].components["hp"]["current"] = 1
    assert world.entities["hero"].components["hp"]["current"] == 10


def test_ability_scores_are_frozen() -> None:
    assert AbilityScores(strength=16).strength == 16
