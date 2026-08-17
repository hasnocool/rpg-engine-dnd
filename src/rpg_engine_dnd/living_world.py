"""v0.4 simulation clocks, weather, factions, schedules, economy, and dynamic events."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .dice import DiceStreams


class WorldClock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minute: int = Field(default=0, ge=0)

    def advance(self, minutes: int) -> int:
        if minutes < 0:
            raise ValueError("minutes must be non-negative")
        self.minute += minutes
        return self.minute

    @property
    def day(self) -> int:
        return self.minute // 1440

    @property
    def minute_of_day(self) -> int:
        return self.minute % 1440


class WeatherState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    temperature_c: float
    visibility: float = Field(default=1.0, ge=0.0, le=1.0)


class WeatherTransition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str
    target: str
    weight: int = Field(default=1, ge=1)


class WeatherSystem:
    def __init__(self, *, seed: int | str | bytes, states: list[WeatherState], transitions: list[WeatherTransition]) -> None:
        self.dice = DiceStreams(seed)
        self.states = {state.name: state for state in states}
        self.transitions = transitions

    def next(self, current: str) -> WeatherState:
        candidates = [edge for edge in self.transitions if edge.source == current]
        if not candidates:
            return self.states[current]
        total = sum(edge.weight for edge in candidates)
        pick = self.dice.stream("weather").randint(1, total)
        cursor = 0
        for edge in sorted(candidates, key=lambda item: item.target):
            cursor += edge.weight
            if pick <= cursor:
                return self.states[edge.target]
        raise AssertionError("weighted weather selection failed")


class Faction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    faction_id: str
    name: str
    reputation: dict[str, int] = Field(default_factory=dict)

    def adjust_reputation(self, actor_id: str, delta: int) -> int:
        value = max(-100, min(100, self.reputation.get(actor_id, 0) + delta))
        self.reputation[actor_id] = value
        return value


class ScheduleEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    start_minute: int = Field(ge=0, lt=1440)
    end_minute: int = Field(gt=0, le=1440)
    location_id: str
    activity: str

    def active(self, minute_of_day: int) -> bool:
        return self.start_minute <= minute_of_day < self.end_minute


class NPCSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[ScheduleEntry] = Field(default_factory=list)

    def current(self, minute_of_day: int) -> ScheduleEntry | None:
        for entry in sorted(self.entries, key=lambda value: value.start_minute):
            if entry.active(minute_of_day):
                return entry
        return None


class MarketItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    base_price: float = Field(gt=0)
    supply: float = Field(default=1.0, ge=0)
    demand: float = Field(default=1.0, ge=0)

    @property
    def price(self) -> float:
        scarcity = (self.demand + 1.0) / (self.supply + 1.0)
        return round(self.base_price * max(0.25, min(4.0, scarcity)), 2)


class Economy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: dict[str, MarketItem] = Field(default_factory=dict)

    def transact(self, item_id: str, quantity: float) -> float:
        if quantity == 0:
            return 0.0
        item = self.items[item_id]
        price = item.price * abs(quantity)
        if quantity > 0:
            if item.supply < quantity:
                raise ValueError("insufficient market supply")
            item.supply -= quantity
            item.demand += quantity * 0.1
        else:
            item.supply += abs(quantity)
        return round(price, 2)


class DynamicEventRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    requires: dict[str, object] = Field(default_factory=dict)
    emits: str
    once: bool = True


class DynamicEventEngine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[DynamicEventRule] = Field(default_factory=list)
    fired: set[str] = Field(default_factory=set)

    def evaluate(self, facts: dict[str, object]) -> list[str]:
        emitted: list[str] = []
        for rule in self.rules:
            if rule.once and rule.event_id in self.fired:
                continue
            if all(facts.get(key) == expected for key, expected in rule.requires.items()):
                emitted.append(rule.emits)
                self.fired.add(rule.event_id)
        return emitted
