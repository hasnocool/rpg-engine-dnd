from rpg_engine_dnd import DiceStreams, ability_modifier, resolve_check


def test_ability_modifier() -> None:
    assert ability_modifier(1) == -5
    assert ability_modifier(10) == 0
    assert ability_modifier(11) == 0
    assert ability_modifier(18) == 4


def test_check_replays_from_same_seed() -> None:
    first = resolve_check(DiceStreams("campaign"), difficulty=15, bonus=3)
    second = resolve_check(DiceStreams("campaign"), difficulty=15, bonus=3)
    assert first == second
