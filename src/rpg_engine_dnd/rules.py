"""v1.2 typed rules runtime, modifiers, effects, hooks, reactions, and action economy."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from .dice import DiceStreams
from .mechanics import Modifier, ModifierResolution, ModifierResolver, ReactionChoice, ReactionStack, ReactionWindow
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
        self.modifier_resolver = ModifierResolver()
        self.modifiers: dict[str, list[Modifier]] = defaultdict(list)
        self.reaction_stack = ReactionStack()

    def register_hook(self, trigger: str, hook: TriggerHook) -> None:
        self._hooks[trigger].append(hook)

    def add_modifier(self, target: str, modifier: Modifier) -> None:
        self.modifiers[target].append(modifier)
        self.modifiers[target].sort(key=lambda item: (item.priority, item.modifier_id))

    def resolve_modifier_value(self, target: str, base: float, *, scope: str | None = None) -> ModifierResolution:
        candidates = self.modifiers.get(target, [])
        if scope is not None:
            candidates = [item for item in candidates if item.scope in {scope, "*"}]
        return self.modifier_resolver.resolve(base, list(candidates))

    @staticmethod
    def _combine_advantage(base: AdvantageState, modifier: int) -> AdvantageState:
        if modifier > 0:
            if base == AdvantageState.DISADVANTAGE:
                return AdvantageState.NORMAL
            return AdvantageState.ADVANTAGE
        if modifier < 0:
            if base == AdvantageState.ADVANTAGE:
                return AdvantageState.NORMAL
            return AdvantageState.DISADVANTAGE
        return base

    def roll(self, context: RollContext) -> RollOutcome:
        traces = (*context.modifiers, ModifierTrace(source="context", value=context.bonus, reason=context.purpose))
        base_bonus = sum(trace.value for trace in traces)
        resolved = self.resolve_modifier_value(context.actor_id, float(base_bonus), scope=context.purpose)
        roll_state = self._combine_advantage(context.advantage, resolved.advantage)
        selected, raw = resolve_d20(
            self.dice,
            state=roll_state,
            stream=f"rules:roll:{context.actor_id}:{context.purpose}",
        )
        total = selected + int(resolved.value)
        if resolved.applied_ids:
            traces = (*traces, ModifierTrace(
                source="modifier-resolver",
                value=int(resolved.value) - base_bonus,
                reason=",".join(resolved.applied_ids),
            ))
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
        resolved = self.resolve_modifier_value(context.target_id, float(amount), scope=f"damage:{context.damage_type}")
        return DamageOutcome(amount=max(0, int(resolved.value)), damage_type=context.damage_type)

    def apply_effect(self, effect: Effect) -> list[Effect]:
        generated: list[Effect] = [effect]
        for hook in self._hooks.get(effect.kind, []):
            generated.extend(hook(effect))
        return generated

    def offer_reaction(self, opportunity: ReactionOpportunity) -> None:
        self.reactions.append(opportunity)

    def open_reaction_window(self, window: ReactionWindow) -> None:
        self.reaction_stack.open(window)

    def offer_reaction_choice(self, choice: ReactionChoice) -> None:
        current = self.reaction_stack.current
        if current is None:
            raise ValueError("no active reaction window")
        current.offer(choice)

    def resolve_reactions(self) -> tuple[ReactionChoice, ...]:
        return self.reaction_stack.resolve_current()

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
