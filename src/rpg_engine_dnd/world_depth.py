"""Deeper adventure, economy, faction, and regional climate simulations."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class ObjectiveStatus(StrEnum):
    LOCKED = "locked"
    ACTIVE = "active"
    COMPLETE = "complete"
    FAILED = "failed"


class ObjectiveNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_id: str
    requires: frozenset[str] = frozenset()
    event_kind: str | None = None
    status: ObjectiveStatus = ObjectiveStatus.LOCKED


class QuestGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest_id: str
    objectives: dict[str, ObjectiveNode] = Field(default_factory=dict)

    def ingest_event(self, kind: str) -> tuple[str, ...]:
        completed = {key for key, node in self.objectives.items() if node.status == ObjectiveStatus.COMPLETE}
        changed: list[str] = []
        for objective_id, node in sorted(self.objectives.items()):
            if node.status == ObjectiveStatus.LOCKED and node.requires.issubset(completed):
                node.status = ObjectiveStatus.ACTIVE
            if node.status == ObjectiveStatus.ACTIVE and node.event_kind == kind:
                node.status = ObjectiveStatus.COMPLETE
                completed.add(objective_id)
                changed.append(objective_id)
        return tuple(changed)


class StoryState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variables: dict[str, object] = Field(default_factory=dict)
    discoveries: set[str] = Field(default_factory=set)
    conversations: dict[str, str] = Field(default_factory=dict)
    locations: dict[str, str] = Field(default_factory=dict)


class ProductionRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    item_id: str
    amount_per_day: float = Field(ge=0)


class ConsumptionRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    item_id: str
    amount_per_day: float = Field(ge=0)


class SettlementMarket(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settlement_id: str
    inventory: dict[str, float] = Field(default_factory=dict)
    base_prices: dict[str, float] = Field(default_factory=dict)
    production: tuple[ProductionRule, ...] = ()
    consumption: tuple[ConsumptionRule, ...] = ()
    scarcity_sensitivity: float = Field(default=0.5, ge=0)

    def simulate_day(self) -> None:
        for production_rule in self.production:
            self.inventory[production_rule.item_id] = (
                self.inventory.get(production_rule.item_id, 0.0) + production_rule.amount_per_day
            )
        for consumption_rule in self.consumption:
            self.inventory[consumption_rule.item_id] = max(
                0.0,
                self.inventory.get(consumption_rule.item_id, 0.0) - consumption_rule.amount_per_day,
            )

    def price(self, item_id: str, *, target_stock: float = 100.0) -> float:
        base = self.base_prices[item_id]
        stock = self.inventory.get(item_id, 0.0)
        scarcity = max(0.25, min(4.0, target_stock / max(1.0, stock)))
        return round(base * (1.0 + self.scarcity_sensitivity * (scarcity - 1.0)), 2)


class TradeRoute(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    route_id: str
    source: str
    target: str
    transport_cost: float = Field(ge=0)
    capacity: float = Field(gt=0)
    blocked: bool = False


class FactionRelation(StrEnum):
    ALLIED = "allied"
    FRIENDLY = "friendly"
    NEUTRAL = "neutral"
    RIVAL = "rival"
    HOSTILE = "hostile"
    WAR = "war"


class FactionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    faction_id: str
    territory: set[str] = Field(default_factory=set)
    resources: dict[str, float] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    military_strength: float = Field(default=0, ge=0)
    influence: float = Field(default=0, ge=0)
    actor_reputation: dict[str, int] = Field(default_factory=dict)


class FactionGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factions: dict[str, FactionState] = Field(default_factory=dict)
    relations: dict[str, FactionRelation] = Field(default_factory=dict)

    @staticmethod
    def _key(left: str, right: str) -> str:
        return "::".join(sorted((left, right)))

    def set_relation(self, left: str, right: str, relation: FactionRelation) -> None:
        self.relations[self._key(left, right)] = relation

    def relation(self, left: str, right: str) -> FactionRelation:
        return self.relations.get(self._key(left, right), FactionRelation.NEUTRAL)


class ClimateProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    climate_id: str
    base_temperature_c: float
    seasonal_amplitude_c: float = Field(default=10.0, ge=0)
    precipitation_bias: float = Field(default=0.5, ge=0, le=1)


class WeatherFront(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    front_id: str
    temperature_delta_c: float = 0
    precipitation: float = Field(default=0, ge=0, le=1)
    wind: float = Field(default=0, ge=0)
    visibility: float = Field(default=1, ge=0, le=1)
    travel_cost_multiplier: float = Field(default=1, ge=0.1)


class WeatherRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_id: str
    climate: ClimateProfile
    season_phase: float = Field(default=0, ge=0, le=1)
    active_front: WeatherFront | None = None

    @property
    def temperature_c(self) -> float:
        seasonal = (self.season_phase * 2.0 - 1.0) * self.climate.seasonal_amplitude_c
        front = self.active_front.temperature_delta_c if self.active_front else 0.0
        return self.climate.base_temperature_c + seasonal + front
