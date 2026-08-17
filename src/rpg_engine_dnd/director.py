"""v2.2 advanced proposal-only campaign director."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class ProposalKind(StrEnum):
    PACING = "pacing"
    ENCOUNTER = "encounter"
    QUEST = "quest"
    FACTION = "faction"
    WORLD = "world"
    DOWNTIME = "downtime"


class DirectorObservation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    campaign_id: str
    sequence: int = Field(ge=0)
    pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    resource_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    unresolved_quests: int = Field(default=0, ge=0)
    faction_motion: int = 0
    idle_minutes: int = Field(default=0, ge=0)


class DirectorProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    proposal_id: str
    kind: ProposalKind
    utility: float
    reason: str
    payload: dict[str, object] = Field(default_factory=dict)


class AdvancedAIDirector:
    """Ranks proposals but has no state mutation interface."""

    def propose(self, observation: DirectorObservation) -> tuple[DirectorProposal, ...]:
        proposals: list[DirectorProposal] = []
        index = 0

        def add(kind: ProposalKind, utility: float, reason: str, payload: dict[str, object] | None = None) -> None:
            nonlocal index
            index += 1
            proposals.append(
                DirectorProposal(
                    proposal_id=f"{observation.campaign_id}:{observation.sequence}:{index}",
                    kind=kind,
                    utility=round(utility, 6),
                    reason=reason,
                    payload={} if payload is None else payload,
                )
            )

        if observation.pressure >= 0.7 or observation.resource_ratio <= 0.35:
            add(ProposalKind.DOWNTIME, 1.5 + observation.pressure, "high pressure or depleted resources", {"mode": "recovery"})
            add(ProposalKind.PACING, 1.2 + observation.pressure, "decompress campaign pacing", {"direction": "down"})
        else:
            add(ProposalKind.ENCOUNTER, 0.8 + (1.0 - observation.pressure), "room for controlled tension")
        if observation.unresolved_quests < 2:
            add(ProposalKind.QUEST, 0.9, "quest load is low")
        if observation.faction_motion:
            add(ProposalKind.FACTION, 0.7 + min(1.0, abs(observation.faction_motion) / 10), "advance faction background state")
        if observation.idle_minutes >= 60:
            add(ProposalKind.WORLD, 0.6 + min(1.0, observation.idle_minutes / 360), "advance background world motion")
        return tuple(sorted(proposals, key=lambda item: (-item.utility, item.proposal_id)))
