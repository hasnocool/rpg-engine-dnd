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
    """Proposal-only director output with enough metadata to simulate before approval."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    proposal_id: str
    kind: ProposalKind
    utility: float
    reason: str
    payload: dict[str, object] = Field(default_factory=dict)
    desired_outcome: str | None = None
    candidate_commands: tuple[dict[str, object], ...] = ()
    cost: float = Field(default=0.0, ge=0.0)
    risk: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expected_world_changes: tuple[str, ...] = ()
    authority_requirements: frozenset[str] = frozenset({"campaign-owner"})


class AdvancedAIDirector:
    """Ranks explainable proposals but has no state mutation interface."""

    def propose(self, observation: DirectorObservation) -> tuple[DirectorProposal, ...]:
        proposals: list[DirectorProposal] = []
        index = 0

        def add(
            kind: ProposalKind,
            utility: float,
            reason: str,
            payload: dict[str, object] | None = None,
            *,
            desired_outcome: str | None = None,
            candidate_commands: tuple[dict[str, object], ...] = (),
            cost: float = 0.0,
            risk: float = 0.0,
            confidence: float = 1.0,
            expected_world_changes: tuple[str, ...] = (),
        ) -> None:
            nonlocal index
            index += 1
            proposals.append(
                DirectorProposal(
                    proposal_id=f"{observation.campaign_id}:{observation.sequence}:{index}",
                    kind=kind,
                    utility=round(utility, 6),
                    reason=reason,
                    payload={} if payload is None else payload,
                    desired_outcome=desired_outcome,
                    candidate_commands=candidate_commands,
                    cost=cost,
                    risk=risk,
                    confidence=confidence,
                    expected_world_changes=expected_world_changes,
                )
            )

        if observation.pressure >= 0.7 or observation.resource_ratio <= 0.35:
            add(
                ProposalKind.DOWNTIME,
                1.5 + observation.pressure,
                "high pressure or depleted resources",
                {"mode": "recovery"},
                desired_outcome="restore player resources and reduce campaign pressure",
                candidate_commands=({"kind": "scene.transition", "scene_type": "downtime"},),
                cost=0.1,
                risk=0.05,
                confidence=0.95,
                expected_world_changes=("downtime scene becomes available", "resource pressure decreases"),
            )
            add(
                ProposalKind.PACING,
                1.2 + observation.pressure,
                "decompress campaign pacing",
                {"direction": "down"},
                desired_outcome="reduce encounter density",
                cost=0.0,
                risk=0.02,
                confidence=0.9,
                expected_world_changes=("pacing pressure decreases",),
            )
        else:
            add(
                ProposalKind.ENCOUNTER,
                0.8 + (1.0 - observation.pressure),
                "room for controlled tension",
                desired_outcome="increase tension without exhausting the party",
                candidate_commands=({"kind": "encounter.prepare", "intensity": "controlled"},),
                cost=max(0.0, 1.0 - observation.resource_ratio),
                risk=min(1.0, 0.2 + observation.pressure * 0.4),
                confidence=0.8,
                expected_world_changes=("encounter candidate becomes available",),
            )
        if observation.unresolved_quests < 2:
            add(
                ProposalKind.QUEST,
                0.9,
                "quest load is low",
                desired_outcome="restore meaningful player choice",
                candidate_commands=({"kind": "quest.propose"},),
                risk=0.05,
                confidence=0.8,
                expected_world_changes=("new quest candidate becomes available",),
            )
        if observation.faction_motion:
            add(
                ProposalKind.FACTION,
                0.7 + min(1.0, abs(observation.faction_motion) / 10),
                "advance faction background state",
                desired_outcome="keep faction simulation responsive to world motion",
                candidate_commands=({"kind": "faction.advance"},),
                risk=0.1,
                confidence=0.75,
                expected_world_changes=("faction background state advances",),
            )
        if observation.idle_minutes >= 60:
            add(
                ProposalKind.WORLD,
                0.6 + min(1.0, observation.idle_minutes / 360),
                "advance background world motion",
                desired_outcome="prevent the persistent world from becoming static",
                candidate_commands=({"kind": "world.advance-background"},),
                risk=0.05,
                confidence=0.85,
                expected_world_changes=("background world state advances",),
            )
        return tuple(sorted(proposals, key=lambda item: (-item.utility, item.proposal_id)))
