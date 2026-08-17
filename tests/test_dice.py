from rpg_engine_dnd import DiceStreams


def test_named_streams_are_reproducible_and_isolated() -> None:
    first = DiceStreams(1234)
    second = DiceStreams(1234)
    assert first.roll("2d6+3", stream="combat") == second.roll("2d6+3", stream="combat")
    baseline = DiceStreams(99)
    expected = baseline.roll("1d20", stream="checks")
    noisy = DiceStreams(99)
    noisy.roll("20d6", stream="weather")
    assert noisy.roll("1d20", stream="checks") == expected


def test_invalid_expression_is_rejected() -> None:
    dice = DiceStreams(1)
    try:
        dice.roll("d20")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid expression should raise")
