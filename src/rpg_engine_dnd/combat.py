"""v0.2 tactical combat, timeline, movement, conditions, inventory, and delayed actions."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Iterable, cast

from pydantic import BaseModel, ConfigDict, Field

from .dice import DiceStreams
from .rules import AttackContext, DamageContext, RulesRuntime
from .scheduler import ScheduleDomain, ScheduledTask, SimulationScheduler
from .spatial import GridSpace
from .spatial_query import SpatialQueryService


class Position(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    x: int
    y: int
    z: int = 0


class Combatant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str = Field(min_length=1)
    initiative_bonus: int = 0
    armor_class: int = Field(default=10, ge=0)
    hit_points: int = Field(default=1, ge=0)
    max_hit_points: int = Field(default=1, ge=1)
    speed: int = Field(default=6, ge=0)
    position: Position = Field(default_factory=lambda: Position(x=0, y=0))


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    rounds_remaining: int = Field(default=1, ge=0)
    periodic_damage: int = Field(default=0, ge=0)


class Item(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: int = Field(default=1, ge=1)
    weight: float = Field(default=0.0, ge=0.0)


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: dict[str, Item] = Field(default_factory=dict)

    def add(self, item: Item) -> None:
        current = self.items.get(item.item_id)
        if current is None:
            self.items[item.item_id] = item
            return
        self.items[item.item_id] = current.model_copy(
            update={"quantity": current.quantity + item.quantity}
        )

    def remove(self, item_id: str, quantity: int = 1) -> Item:
        if quantity < 1:
            raise ValueError("quantity must be positive")
        current = self.items[item_id]
        if quantity > current.quantity:
            raise ValueError("insufficient quantity")
        removed = current.model_copy(update={"quantity": quantity})
        remaining = current.quantity - quantity
        if remaining == 0:
            del self.items[item_id]
        else:
            self.items[item_id] = current.model_copy(update={"quantity": remaining})
        return removed


@dataclass(order=True, slots=True)
class TimelineAction:
    due_tick: int
    order: int
    actor_id: str = field(compare=False)
    kind: str = field(compare=False)
    payload: dict[str, object] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class AttackResult:
    attacker_id: str
    target_id: str
    d20: int
    total: int
    hit: bool
    damage: int


class CombatSystem:
    """Deterministic tactical resolver backed by shared rules/spatial/time services when provided."""

    def __init__(
        self,
        seed: int | str | bytes,
        *,
        rules_runtime: RulesRuntime | None = None,
        scheduler: SimulationScheduler | None = None,
        spatial_queries: SpatialQueryService | None = None,
        grid_space: GridSpace | None = None,
    ) -> None:
        self.dice = DiceStreams(seed)
        self.rules_runtime = rules_runtime
        self.scheduler = scheduler
        self.spatial_queries = spatial_queries or SpatialQueryService()
        self.grid_space = grid_space
        self.combatants: dict[str, Combatant] = {}
        self.conditions: dict[str, list[Condition]] = {}
        self.inventories: dict[str, Inventory] = {}
        self.initiative: list[str] = []
        self.tick = scheduler.tick if scheduler is not None else 0
        self._queue: list[TimelineAction] = []
        self._order = 0

    def register(self, combatant: Combatant) -> None:
        if combatant.actor_id in self.combatants:
            raise ValueError(f"combatant already registered: {combatant.actor_id}")
        self.combatants[combatant.actor_id] = combatant.model_copy(deep=True)
        self.conditions[combatant.actor_id] = []
        self.inventories[combatant.actor_id] = Inventory()
        if self.grid_space is not None:
            position = combatant.position
            if position.z != 0:
                raise ValueError("GridSpace combat currently requires z=0 positions")
            self.grid_space.occupy(combatant.actor_id, (position.x, position.y))

    def start(self) -> list[str]:
        scores: list[tuple[int, str]] = []
        for actor_id, combatant in sorted(self.combatants.items()):
            roll = self.dice.roll("1d20", stream=f"initiative:{actor_id}").total
            scores.append((roll + combatant.initiative_bonus, actor_id))
        scores.sort(key=lambda pair: (-pair[0], pair[1]))
        self.initiative = [actor_id for _, actor_id in scores]
        return list(self.initiative)

    @staticmethod
    def path(start: Position, goal: Position, *, blocked: Iterable[Position] = ()) -> list[Position]:
        """Legacy unbounded-grid path helper retained for API compatibility."""
        blocked_set = {(p.x, p.y, p.z) for p in blocked}
        if (goal.x, goal.y, goal.z) in blocked_set:
            raise ValueError("goal is blocked")
        frontier: list[tuple[int, int, int, int, Position]] = []
        heapq.heappush(frontier, (0, 0, start.x, start.y, start))
        parent: dict[tuple[int, int, int], tuple[int, int, int] | None] = {
            (start.x, start.y, start.z): None
        }
        cost = {(start.x, start.y, start.z): 0}
        goal_key = (goal.x, goal.y, goal.z)
        while frontier:
            _, current_cost, _, _, current = heapq.heappop(frontier)
            key = (current.x, current.y, current.z)
            if key == goal_key:
                break
            for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
                nxt = Position(x=current.x + dx, y=current.y + dy, z=current.z)
                nkey = (nxt.x, nxt.y, nxt.z)
                if nkey in blocked_set:
                    continue
                new_cost = current_cost + 1
                if nkey in cost and new_cost >= cost[nkey]:
                    continue
                cost[nkey] = new_cost
                parent[nkey] = key
                heuristic = abs(goal.x - nxt.x) + abs(goal.y - nxt.y)
                heapq.heappush(frontier, (new_cost + heuristic, new_cost, nxt.x, nxt.y, nxt))
        if goal_key not in parent:
            raise ValueError("no path")
        reversed_path: list[Position] = []
        cursor: tuple[int, int, int] | None = goal_key
        while cursor is not None:
            reversed_path.append(Position(x=cursor[0], y=cursor[1], z=cursor[2]))
            cursor = parent[cursor]
        return list(reversed(reversed_path))

    @staticmethod
    def line_of_sight(start: Position, goal: Position, *, blocked: Iterable[Position] = ()) -> bool:
        """Legacy Bresenham helper retained for API compatibility."""
        blockers = {(p.x, p.y, p.z) for p in blocked}
        x0, y0, x1, y1 = start.x, start.y, goal.x, goal.y
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            if (x0, y0) not in {(start.x, start.y), (goal.x, goal.y)}:
                if (x0, y0, start.z) in blockers:
                    return False
            if x0 == x1 and y0 == y1:
                return True
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x0 += sx
            if doubled <= dx:
                error += dx
                y0 += sy

    def authoritative_path(
        self,
        start: Position,
        goal: Position,
        *,
        budget: float | None = None,
        blocked: Iterable[Position] = (),
    ) -> list[Position]:
        if self.grid_space is None:
            return self.path(start, goal, blocked=blocked)
        if start.z != 0 or goal.z != 0:
            raise ValueError("GridSpace combat currently requires z=0 positions")
        space = self.grid_space.model_copy(deep=True)
        for blocker in blocked:
            if blocker.z != 0:
                continue
            try:
                cell = space.cell(blocker.x, blocker.y)
            except ValueError:
                continue
            space.cells[(blocker.x, blocker.y)] = cell.model_copy(update={"blocks_movement": True})
        raw_path = self.spatial_queries.path(
            space,
            (start.x, start.y),
            (goal.x, goal.y),
            budget=budget,
        )
        coordinates = cast(list[tuple[int, int]], raw_path)
        return [Position(x=coordinate[0], y=coordinate[1]) for coordinate in coordinates]

    def authoritative_line_of_sight(self, start: Position, goal: Position) -> bool:
        if self.grid_space is None:
            return self.line_of_sight(start, goal)
        if start.z != 0 or goal.z != 0:
            return False
        return self.spatial_queries.visible(self.grid_space, (start.x, start.y), (goal.x, goal.y))

    def move(self, actor_id: str, destination: Position, *, blocked: Iterable[Position] = ()) -> list[Position]:
        actor = self.combatants[actor_id]
        path = self.authoritative_path(actor.position, destination, budget=float(actor.speed), blocked=blocked)
        steps = len(path) - 1
        if self.grid_space is None and steps > actor.speed:
            raise ValueError("movement budget exceeded")
        if self.grid_space is not None:
            self.grid_space.occupy(actor_id, (destination.x, destination.y))
        actor.position = destination
        return path

    def attack(
        self,
        attacker_id: str,
        target_id: str,
        *,
        attack_bonus: int = 0,
        damage_expression: str = "1d6",
    ) -> AttackResult:
        attacker = self.combatants[attacker_id]
        target = self.combatants[target_id]
        if attacker.hit_points <= 0:
            raise ValueError("incapacitated attacker")
        if self.rules_runtime is not None:
            attack_outcome = self.rules_runtime.attack(
                AttackContext(
                    attacker_id=attacker_id,
                    target_id=target_id,
                    armor_class=target.armor_class,
                    attack_bonus=attack_bonus,
                )
            )
            d20 = attack_outcome.roll.selected
            total = attack_outcome.roll.total
            hit = attack_outcome.hit
            damage = (
                self.rules_runtime.damage(
                    DamageContext(
                        source_id=attacker_id,
                        target_id=target_id,
                        expression=damage_expression,
                    )
                ).amount
                if hit
                else 0
            )
        else:
            d20 = self.dice.roll("1d20", stream=f"attack:{attacker_id}").total
            total = d20 + attack_bonus
            hit = total >= target.armor_class
            damage = (
                self.dice.roll(damage_expression, stream=f"damage:{attacker_id}").total
                if hit
                else 0
            )
        if hit:
            target.hit_points = max(0, target.hit_points - damage)
        return AttackResult(attacker_id, target_id, d20, total, hit, damage)

    def add_condition(self, actor_id: str, condition: Condition) -> None:
        self.conditions[actor_id].append(condition.model_copy(deep=True))

    @staticmethod
    def _schedule_domain(kind: str) -> ScheduleDomain:
        lowered = kind.lower()
        if "spell" in lowered:
            return ScheduleDomain.SPELL
        if "condition" in lowered or "effect" in lowered:
            return ScheduleDomain.CONDITION
        return ScheduleDomain.TURN

    def schedule(self, actor_id: str, kind: str, *, delay_ticks: int, payload: dict[str, object] | None = None) -> TimelineAction:
        if delay_ticks < 0:
            raise ValueError("delay_ticks must be non-negative")
        self._order += 1
        base_tick = self.scheduler.tick if self.scheduler is not None else self.tick
        action = TimelineAction(
            due_tick=base_tick + delay_ticks,
            order=self._order,
            actor_id=actor_id,
            kind=kind,
            payload={} if payload is None else dict(payload),
        )
        if self.scheduler is None:
            heapq.heappush(self._queue, action)
        else:
            scheduled_payload = dict(action.payload)
            scheduled_payload["combat_order"] = action.order
            self.scheduler.schedule(
                f"combat:{action.order}:{actor_id}:{kind}",
                delay_ticks=delay_ticks,
                domain=self._schedule_domain(kind),
                kind=kind,
                actor_id=actor_id,
                payload=scheduled_payload,
            )
        return action

    def _advance_conditions_once(self) -> None:
        for actor_id, active in self.conditions.items():
            updated: list[Condition] = []
            for condition in active:
                if condition.periodic_damage:
                    actor = self.combatants[actor_id]
                    actor.hit_points = max(0, actor.hit_points - condition.periodic_damage)
                remaining = max(0, condition.rounds_remaining - 1)
                if remaining:
                    updated.append(condition.model_copy(update={"rounds_remaining": remaining}))
            self.conditions[actor_id] = updated

    def apply_scheduled(self, tasks: Iterable[ScheduledTask]) -> list[TimelineAction]:
        """Consume only combat-tagged tasks after the platform advances the shared scheduler."""
        if self.scheduler is None:
            raise RuntimeError("combat is not attached to a shared scheduler")
        delta = self.scheduler.tick - self.tick
        if delta < 0:
            raise RuntimeError("shared scheduler moved backwards")
        for _ in range(delta):
            self._advance_conditions_once()
        self.tick = self.scheduler.tick
        ready: list[TimelineAction] = []
        for task in tasks:
            order_raw = task.payload.get("combat_order")
            if task.actor_id is None or not isinstance(order_raw, int) or not task.task_id.startswith("combat:"):
                continue
            payload = {key: value for key, value in task.payload.items() if key != "combat_order"}
            ready.append(
                TimelineAction(
                    due_tick=task.due_tick,
                    order=order_raw,
                    actor_id=task.actor_id,
                    kind=task.kind,
                    payload=payload,
                )
            )
        return sorted(ready)

    def advance(self, ticks: int = 1) -> list[TimelineAction]:
        if ticks < 0:
            raise ValueError("ticks must be non-negative")
        if self.scheduler is not None:
            raise RuntimeError("shared SimulationScheduler must be advanced by the platform authority")
        ready: list[TimelineAction] = []
        for _ in range(ticks):
            self.tick += 1
            self._advance_conditions_once()
            while self._queue and self._queue[0].due_tick <= self.tick:
                ready.append(heapq.heappop(self._queue))
        return ready

    @staticmethod
    def distance(a: Position, b: Position) -> float:
        return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))

    def authoritative_distance(self, a: Position, b: Position) -> float:
        if self.grid_space is not None and a.z == 0 and b.z == 0:
            return self.spatial_queries.distance(self.grid_space, (a.x, a.y), (b.x, b.y))
        return self.distance(a, b)
