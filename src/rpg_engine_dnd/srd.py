"""v1.1 SRD 5.2.1 compatibility helpers with an explicit provenance boundary.

This module implements mechanics and structured references only. It intentionally does
not reproduce rulebook prose. Projects that distribute SRD content should attach their
own appropriately licensed source data and attribution.
"""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

from .dice import DiceStreams


class SRDProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_id: str = "srd-5.2.1"
    license_id: str = "CC-BY-4.0"
    source_url: str | None = None
    attribution: str | None = None
    enabled: bool = False


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entry_id: str
    name: str
    metadata: dict[str, object] = Field(default_factory=dict)


class SRDCatalogs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills: dict[str, CatalogEntry] = Field(default_factory=dict)
    classes: dict[str, CatalogEntry] = Field(default_factory=dict)
    species: dict[str, CatalogEntry] = Field(default_factory=dict)
    backgrounds: dict[str, CatalogEntry] = Field(default_factory=dict)
    feats: dict[str, CatalogEntry] = Field(default_factory=dict)

    @classmethod
    def structural_defaults(cls) -> "SRDCatalogs":
        """Return names/identifiers useful for integration without copying prose."""
        skills = [
            "acrobatics", "animal-handling", "arcana", "athletics", "deception",
            "history", "insight", "intimidation", "investigation", "medicine",
            "nature", "perception", "performance", "persuasion", "religion",
            "sleight-of-hand", "stealth", "survival",
        ]
        classes = [
            "barbarian", "bard", "cleric", "druid", "fighter", "monk",
            "paladin", "ranger", "rogue", "sorcerer", "warlock", "wizard",
        ]
        return cls(
            skills={key: CatalogEntry(entry_id=key, name=key.replace("-", " ").title()) for key in skills},
            classes={key: CatalogEntry(entry_id=key, name=key.title()) for key in classes},
        )


class AdvantageState(StrEnum):
    DISADVANTAGE = "disadvantage"
    NORMAL = "normal"
    ADVANTAGE = "advantage"


def proficiency_bonus(level: int) -> int:
    if level < 1:
        raise ValueError("level must be positive")
    return 2 + (level - 1) // 4


def resolve_d20(dice: DiceStreams, *, state: AdvantageState = AdvantageState.NORMAL, stream: str = "srd:d20") -> tuple[int, tuple[int, ...]]:
    if state == AdvantageState.NORMAL:
        value = dice.roll("1d20", stream=stream).total
        return value, (value,)
    rolls = (
        dice.roll("1d20", stream=stream).total,
        dice.roll("1d20", stream=stream).total,
    )
    return (max(rolls) if state == AdvantageState.ADVANTAGE else min(rolls)), rolls


class DamageTrait(StrEnum):
    RESISTANCE = "resistance"
    IMMUNITY = "immunity"
    VULNERABILITY = "vulnerability"


def apply_damage_trait(amount: int, trait: DamageTrait | None) -> int:
    if amount < 0:
        raise ValueError("damage cannot be negative")
    if trait == DamageTrait.IMMUNITY:
        return 0
    if trait == DamageTrait.RESISTANCE:
        return amount // 2
    if trait == DamageTrait.VULNERABILITY:
        return amount * 2
    return amount


class HitPointState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: int = Field(ge=0)
    maximum: int = Field(ge=1)
    temporary: int = Field(default=0, ge=0)
    death_successes: int = Field(default=0, ge=0, le=3)
    death_failures: int = Field(default=0, ge=0, le=3)

    def damage(self, amount: int) -> int:
        if amount < 0:
            raise ValueError("damage cannot be negative")
        absorbed = min(self.temporary, amount)
        self.temporary -= absorbed
        remaining = amount - absorbed
        self.current = max(0, self.current - remaining)
        return remaining

    def grant_temporary(self, amount: int) -> None:
        if amount < 0:
            raise ValueError("temporary hit points cannot be negative")
        self.temporary = max(self.temporary, amount)

    def record_death_save(self, success: bool) -> str:
        if self.current > 0:
            raise ValueError("death saves require zero hit points")
        if success:
            self.death_successes = min(3, self.death_successes + 1)
        else:
            self.death_failures = min(3, self.death_failures + 1)
        if self.death_successes >= 3:
            return "stable"
        if self.death_failures >= 3:
            return "dead"
        return "pending"


ROUND_SECONDS = 6


class StructuredCondition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    condition_id: str
    source_id: str | None = None
    duration_rounds: int | None = Field(default=None, ge=0)
    tags: frozenset[str] = frozenset()
