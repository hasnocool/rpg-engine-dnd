"""Knowledge provenance graph for rumors, lies, stealth, illusions, and shared intelligence."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class Visibility(StrEnum):
    PRIVATE = "private"
    PARTY = "party"
    FACTION = "faction"
    PUBLIC = "public"


class KnownFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fact_id: str
    subject: str
    predicate: str
    value: object
    source: str
    observed_at: int = Field(ge=0)
    confidence: float = Field(default=1, ge=0, le=1)
    expires_at: int | None = Field(default=None, ge=0)
    derived_from: tuple[str, ...] = ()
    visibility: Visibility = Visibility.PRIVATE
    deceptive: bool = False

    def active(self, sequence: int) -> bool:
        return self.expires_at is None or sequence < self.expires_at


class KnowledgeGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: dict[str, KnownFact] = Field(default_factory=dict)

    def add(self, fact: KnownFact) -> None:
        self.facts[fact.fact_id] = fact

    def query(self, subject: str, predicate: str | None = None, *, sequence: int) -> tuple[KnownFact, ...]:
        result = [
            fact
            for fact in self.facts.values()
            if fact.subject == subject
            and (predicate is None or fact.predicate == predicate)
            and fact.active(sequence)
        ]
        return tuple(sorted(result, key=lambda item: (-item.confidence, -item.observed_at, item.fact_id)))

    def shareable(self, visibility: Visibility, *, sequence: int) -> tuple[KnownFact, ...]:
        levels = {
            Visibility.PRIVATE: 0,
            Visibility.PARTY: 1,
            Visibility.FACTION: 2,
            Visibility.PUBLIC: 3,
        }
        threshold = levels[visibility]
        result = [
            fact for fact in self.facts.values()
            if fact.active(sequence) and levels[fact.visibility] >= threshold
        ]
        return tuple(sorted(result, key=lambda item: item.fact_id))
