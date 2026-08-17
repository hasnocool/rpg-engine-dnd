"""v1.2 typed rules runtime, modifiers, effects, hooks, reactions, and action economy."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from .dice import DiceStreams
from .srd import AdvantageState, resolve_d20


class ModifierTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str
    value: int
    reason: str


class RollContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    actor_id: str
    purpose: str
    bonus: int = 0
    advantage: AdvantageState = AdvantageState.NORMAL
    modifiers: tuple[ModifierTrace, ...] = ()


class RollOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    raw_rolls: tuple[int, ...]
    selected: int
    total: int
    traces: tuple[ModifierTrace, ...]


class AttackContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    attacker_id: str
    target_id: str
    armor_class: int = Field(ge=0)
    attack_bonus: int = 0
    advantage: AdvantageState = AdvantageState.NORMAL


class AttackOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    roll: RollOutcome
    hit: bool


class DamageContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_id: str
    target_id: str
    expression: str
    damage_type: str = "untyped"


class DamageOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    amount: int = Field(ge=0)
    damage_type: str


class Effect(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    effect_id: str
    source_id: str
    target_id: str
    kind: str
    payload: dict[str, object] = Field(default_factory=dict)


class ReactionOpportunity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reaction_id: str
    actor_id: str
    trigger: str
    expires_at_sequence: int | None = None


class ActionEconomy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: int = Field(default=1, ge=0)
    bonus_action: int = Field(default=1, ge=0)
    reaction: int = Field(default=1, ge=0)
    movement: int = Field(default=0, ge=0)

    def spend(self, resource: str, amount: int = 1) -> None:
        if amount < 1 or resource not in {"action", "bonus_action", "reaction", "movement"}:
            raise ValueError("invalid action-economy spend")
        current = int(getattr(self, resource))
        if current < amount:
            raise ValueError(f"insufficient {resource}")
        setattr(self, resource, current - amount)


class RulesetCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    capability_ids: frozenset[str] = frozenset()

    def require(self, capability: str) -> None:
        if capability not in self.capability_ids:
            raise ValueError(f"ruleset lacks capability: {capability}")


TriggerHook = Callable[[Effect], list[Effect]]


class RulesRuntime:
    """Typed deterministic runtime that owns roll/effect mechanics, not presentation."""

    def __init__(self, *, seed: int | str | bytes, capabilities: RulesetCapabilities | None = None) -> None:
        self.dice = DiceStreams(seed)
        self.capabilities = capabilities or RulesetCapabilities()
        self._hooks: dict[str, list[TriggerHook]] = defaultdict(list)
        self.reactions: list[ReactionOpportunity] = []
        self.action_economy: dict[str, ActionEconomy] = {}

    def register_hook(self, trigger: str, hook: TriggerHook) -> None:
        self._hooks[trigger].append(hook)

    def roll(self, context: RollContext) -> RollOutcome:
        selected, raw = resolve_d20(
            self.dice,
            state=context.advantage,
            stream=f"rules:roll:{context.actor_id}:{context.purpose}",
        )
        traces = (*context.modifiers, ModifierTrace(source="context", value=context.bonus, reason=context.purpose))
        total = selected + sum(trace.value for trace in traces)
        return RollOutcome(raw_rolls=raw, selected=selected, total=total, traces=traces)

    def attack(self, context: AttackContext) -> AttackOutcome:
        outcome = self.roll(
            RollContext(
                actor_id=context.attacker_id,
                purpose="attack",
                bonus=context.attack_bonus,
                advantage=context.advantage,
            )
        )
        return AttackOutcome(roll=outcome, hit=outcome.total >= context.armor_class)

    def damage(self, context: DamageContext) -> DamageOutcome:
        amount = self.dice.roll(
            context.expression,
            stream=f"rules:damage:{context.source_id}:{context.target_id}",
        ).total
        return DamageOutcome(amount=max(0, amount), damage_type=context.damage_type)

    def apply_effect(self, effect: Effect) -> list[Effect]:
        generated: list[Effect] = [effect]
        for hook in self._hooks.get(effect.kind, []):
            generated.extend(hook(effect))
        return generated

    def offer_reaction(self, opportunity: ReactionOpportunity) -> None:
        self.reactions.append(opportunity)

    def reset_turn(self, actor_id: str, *, movement: int) -> ActionEconomy:
        economy = ActionEconomy(movement=movement)
        self.action_economy[actor_id] = economy
        return economy


class SRDRulesRuntime(RulesRuntime):
    def __init__(self, *, seed: int | str | bytes) -> None:
        super().__init__(
            seed=seed,
            capabilities=RulesetCapabilities(
                capability_ids=frozenset({
                    "advantage", "reactions", "action-economy", "conditions", "death-saves"
                })
            ),
        )
