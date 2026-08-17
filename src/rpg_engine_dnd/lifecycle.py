"""v1.6 rules-neutral character construction, progression, rest, resources, and equipment."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CharacterBuild(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: str
    name: str
    species_id: str | None = None
    background_id: str | None = None
    ability_scores: dict[str, int] = Field(default_factory=dict)
    class_levels: dict[str, int] = Field(default_factory=dict)

    @property
    def level(self) -> int:
        return sum(self.class_levels.values())

    def add_class_level(self, class_id: str) -> int:
        self.class_levels[class_id] = self.class_levels.get(class_id, 0) + 1
        return self.level


class ProgressionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(default=1, ge=1)
    experience: int = Field(default=0, ge=0)
    milestones: int = Field(default=0, ge=0)
    features: set[str] = Field(default_factory=set)
    unspent_ability_points: int = Field(default=0, ge=0)


class AdvancementOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    old_level: int
    new_level: int
    hit_point_gain: int = Field(ge=0)
    gained_features: tuple[str, ...] = ()
    ability_points_granted: int = Field(default=0, ge=0)


class ProgressionTrack:
    def __init__(self, xp_thresholds: dict[int, int] | None = None) -> None:
        self.xp_thresholds = dict(xp_thresholds or {1: 0})

    def level_for_xp(self, experience: int) -> int:
        eligible = [level for level, threshold in self.xp_thresholds.items() if experience >= threshold]
        return max(eligible, default=1)

    def add_xp(self, state: ProgressionState, amount: int) -> int:
        if amount < 0:
            raise ValueError("experience amount must be non-negative")
        state.experience += amount
        return self.level_for_xp(state.experience)

    def add_milestone(self, state: ProgressionState, count: int = 1) -> int:
        if count < 1:
            raise ValueError("milestone count must be positive")
        state.milestones += count
        return state.milestones

    def advance(
        self,
        state: ProgressionState,
        *,
        to_level: int,
        hit_point_gain: int,
        features: tuple[str, ...] = (),
        ability_points: int = 0,
    ) -> AdvancementOutcome:
        if to_level <= state.level:
            raise ValueError("new level must exceed current level")
        if hit_point_gain < 0 or ability_points < 0:
            raise ValueError("advancement gains cannot be negative")
        old = state.level
        state.level = to_level
        state.features.update(features)
        state.unspent_ability_points += ability_points
        return AdvancementOutcome(
            old_level=old,
            new_level=to_level,
            hit_point_gain=hit_point_gain,
            gained_features=features,
            ability_points_granted=ability_points,
        )


class ResourcePool(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: str
    current: int = Field(ge=0)
    maximum: int = Field(ge=0)
    recover_short: int | None = Field(default=None, ge=0)
    recover_long: int | None = Field(default=None, ge=0)

    def spend(self, amount: int = 1) -> None:
        if amount < 1 or self.current < amount:
            raise ValueError("insufficient resource")
        self.current -= amount

    def recover(self, rest: str) -> None:
        amount = self.recover_short if rest == "short" else self.recover_long if rest == "long" else None
        if amount is None:
            return
        self.current = min(self.maximum, self.current + amount)


class EquipmentItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    item_id: str
    slot: str | None = None
    attunement_required: bool = False
    modifiers: dict[str, int] = Field(default_factory=dict)


class EquipmentState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    equipped: dict[str, EquipmentItem] = Field(default_factory=dict)
    attuned: set[str] = Field(default_factory=set)
    max_attuned: int = Field(default=3, ge=0)

    def equip(self, item: EquipmentItem) -> EquipmentItem | None:
        if item.slot is None:
            raise ValueError("item has no equipment slot")
        displaced = self.equipped.get(item.slot)
        self.equipped[item.slot] = item
        return displaced

    def attune(self, item: EquipmentItem) -> None:
        if not item.attunement_required:
            raise ValueError("item does not require attunement")
        if item.item_id not in {equipped.item_id for equipped in self.equipped.values()}:
            raise ValueError("item must be equipped before attunement")
        if item.item_id not in self.attuned and len(self.attuned) >= self.max_attuned:
            raise ValueError("attunement limit exceeded")
        self.attuned.add(item.item_id)

    def aggregate_modifiers(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for item in self.equipped.values():
            if item.attunement_required and item.item_id not in self.attuned:
                continue
            for key, value in item.modifiers.items():
                totals[key] = totals.get(key, 0) + value
        return totals


class CharacterLifecycle(BaseModel):
    """Serializable component bundle suitable for normal entity-component storage."""

    model_config = ConfigDict(extra="forbid")
    build: CharacterBuild
    progression: ProgressionState = Field(default_factory=ProgressionState)
    resources: dict[str, ResourcePool] = Field(default_factory=dict)
    equipment: EquipmentState = Field(default_factory=EquipmentState)

    def rest(self, kind: str) -> None:
        if kind not in {"short", "long"}:
            raise ValueError("unknown rest kind")
        for resource in self.resources.values():
            resource.recover(kind)
