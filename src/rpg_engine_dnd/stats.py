"""Stat and check helpers kept deterministic and side-effect free."""

from __future__ import annotations

from dataclasses import dataclass

from .dice import DiceRoll, DiceStreams


def ability_modifier(score: int) -> int:
    if score < 1:
        raise ValueError("ability score must be positive")
    return (score - 10) // 2


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    roll: DiceRoll
    bonus: int
    difficulty: int
    total: int
    success: bool


def resolve_check(dice: DiceStreams, *, difficulty: int, bonus: int = 0, stream: str = "checks") -> CheckOutcome:
    if difficulty < 0:
        raise ValueError("difficulty must be non-negative")
    roll = dice.roll("1d20", stream=stream)
    total = roll.total + bonus
    return CheckOutcome(roll, bonus, difficulty, total, total >= difficulty)
