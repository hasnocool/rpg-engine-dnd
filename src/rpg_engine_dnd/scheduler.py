"""Deterministic universal simulation scheduler for all game-time domains."""

from __future__ import annotations

import asyncio
import heapq
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ScheduleDomain(StrEnum):
    TURN = "turn"
    SPELL = "spell"
    CONDITION = "condition"
    AI = "ai"
    NPC = "npc"
    QUEST = "quest"
    WEATHER = "weather"
    TRAVEL = "travel"
    DOWNTIME = "downtime"
    CRAFTING = "crafting"
    REST = "rest"
    RESPAWN = "respawn"
    WORLD = "world"
    SHARD = "shard"


@dataclass(order=True, frozen=True, slots=True)
class ScheduledTask:
    due_tick: int
    order: int
    task_id: str = field(compare=False)
    domain: ScheduleDomain = field(compare=False)
    kind: str = field(compare=False)
    actor_id: str | None = field(default=None, compare=False)
    payload: dict[str, Any] = field(default_factory=dict, compare=False)


class SimulationScheduler:
    """One deterministic timeline shared by combat, world, AI, and hosting systems."""

    def __init__(self, *, tick: int = 0) -> None:
        if tick < 0:
            raise ValueError("tick must be non-negative")
        self.tick = tick
        self._order = 0
        self._queue: list[ScheduledTask] = []
        self._cancelled: set[str] = set()
        self._ids: set[str] = set()
        self._lock = asyncio.Lock()

    def schedule(
        self,
        task_id: str,
        *,
        delay_ticks: int,
        domain: ScheduleDomain,
        kind: str,
        actor_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ScheduledTask:
        if delay_ticks < 0:
            raise ValueError("delay_ticks must be non-negative")
        if task_id in self._ids:
            raise ValueError(f"duplicate scheduled task id: {task_id}")
        self._order += 1
        task = ScheduledTask(
            due_tick=self.tick + delay_ticks,
            order=self._order,
            task_id=task_id,
            domain=domain,
            kind=kind,
            actor_id=actor_id,
            payload={} if payload is None else dict(payload),
        )
        self._ids.add(task_id)
        heapq.heappush(self._queue, task)
        return task

    def cancel(self, task_id: str) -> bool:
        if task_id not in self._ids:
            return False
        self._cancelled.add(task_id)
        return True

    def advance(self, ticks: int = 1) -> tuple[ScheduledTask, ...]:
        if ticks < 0:
            raise ValueError("ticks must be non-negative")
        self.tick += ticks
        ready: list[ScheduledTask] = []
        while self._queue and self._queue[0].due_tick <= self.tick:
            task = heapq.heappop(self._queue)
            self._ids.discard(task.task_id)
            if task.task_id in self._cancelled:
                self._cancelled.remove(task.task_id)
                continue
            ready.append(task)
        return tuple(ready)

    async def schedule_async(self, *args: Any, **kwargs: Any) -> ScheduledTask:
        async with self._lock:
            return self.schedule(*args, **kwargs)

    async def advance_async(self, ticks: int = 1) -> tuple[ScheduledTask, ...]:
        async with self._lock:
            return self.advance(ticks)

    def pending(self) -> tuple[ScheduledTask, ...]:
        return tuple(sorted(task for task in self._queue if task.task_id not in self._cancelled))
