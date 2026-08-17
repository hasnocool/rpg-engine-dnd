"""Deterministic, isolated dice streams."""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass

_DICE = re.compile(r"^(?P<count>[1-9]\\d*)d(?P<sides>[1-9]\\d*)(?P<bonus>[+-]\\d+)?$")


@dataclass(frozen=True, slots=True)
class DiceRoll:
    expression: str
    rolls: tuple[int, ...]
    modifier: int
    total: int


class DiceStreams:
    """Deterministic RNG namespace keyed by a root seed and stream name."""

    def __init__(self, seed: int | str | bytes) -> None:
        self._seed = seed if isinstance(seed, bytes) else str(seed).encode("utf-8")
        self._streams: dict[str, random.Random] = {}

    def _stream_seed(self, name: str) -> int:
        if not name:
            raise ValueError("stream name must not be empty")
        digest = hashlib.sha256(self._seed + b"\\x00" + name.encode("utf-8")).digest()
        return int.from_bytes(digest, "big")

    def stream(self, name: str) -> random.Random:
        try:
            return self._streams[name]
        except KeyError:
            rng = random.Random(self._stream_seed(name))
            self._streams[name] = rng
            return rng

    def roll(self, expression: str, *, stream: str = "default") -> DiceRoll:
        match = _DICE.fullmatch(expression.strip().lower())
        if match is None:
            raise ValueError(f"invalid dice expression: {expression!r}")
        count = int(match.group("count"))
        sides = int(match.group("sides"))
        modifier = int(match.group("bonus") or 0)
        if count > 1_000 or sides > 1_000_000:
            raise ValueError("dice expression exceeds safety limit")
        rolls = tuple(self.stream(stream).randint(1, sides) for _ in range(count))
        return DiceRoll(expression, rolls, modifier, sum(rolls) + modifier)
