"""Unified spatial query façade plus deterministic axial hex-grid authority."""

from __future__ import annotations

import heapq
from math import dist
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from .spatial import ContinuousSpace, GraphSpace, GridSpace


class HexCell(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    q: int
    r: int
    movement_cost: float = Field(default=1.0, gt=0)
    blocked: bool = False
    cover: int = Field(default=0, ge=0, le=3)


class HexGridSpace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cells: dict[tuple[int, int], HexCell] = Field(default_factory=dict)
    occupancy: dict[tuple[int, int], str] = Field(default_factory=dict)

    @staticmethod
    def neighbors(point: tuple[int, int]) -> tuple[tuple[int, int], ...]:
        q, r = point
        return ((q + 1, r), (q - 1, r), (q, r + 1), (q, r - 1), (q + 1, r - 1), (q - 1, r + 1))

    @staticmethod
    def distance(a: tuple[int, int], b: tuple[int, int]) -> int:
        aq, ar = a
        bq, br = b
        return max(abs(aq - bq), abs(ar - br), abs((aq + ar) - (bq + br)))

    def path(self, start: tuple[int, int], goal: tuple[int, int], *, budget: float | None = None) -> list[tuple[int, int]]:
        """Find the minimum-cost path with Dijkstra ordering.

        Cell movement costs may be below one, so raw hex distance is not a generally
        admissible A* heuristic. Cost-only ordering preserves optimality for every
        positive movement cost supported by ``HexCell``.
        """
        frontier: list[tuple[float, tuple[int, int]]] = [(0.0, start)]
        costs = {start: 0.0}
        parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        while frontier:
            current_cost, current = heapq.heappop(frontier)
            if current_cost > costs.get(current, float("inf")):
                continue
            if current == goal:
                break
            for neighbor in sorted(self.neighbors(current)):
                cell = self.cells.get(neighbor, HexCell(q=neighbor[0], r=neighbor[1]))
                if cell.blocked or (neighbor in self.occupancy and neighbor != goal):
                    continue
                new_cost = current_cost + cell.movement_cost
                if budget is not None and new_cost > budget:
                    continue
                if new_cost < costs.get(neighbor, float("inf")):
                    costs[neighbor] = new_cost
                    parents[neighbor] = current
                    heapq.heappush(frontier, (new_cost, neighbor))
        if goal not in parents:
            raise ValueError("no hex path")
        result: list[tuple[int, int]] = []
        cursor: tuple[int, int] | None = goal
        while cursor is not None:
            result.append(cursor)
            cursor = parents[cursor]
        return list(reversed(result))


class SpatialQueryService:
    def path(self, space: GraphSpace | GridSpace | HexGridSpace, start: object, goal: object, *, budget: float | None = None) -> list[object]:
        if isinstance(space, GraphSpace):
            return list(space.route(str(start), str(goal)))
        coordinates = cast(tuple[int, int], start)
        destination = cast(tuple[int, int], goal)
        if isinstance(space, GridSpace):
            return list(space.path(coordinates, destination, budget=budget))
        return list(space.path(coordinates, destination, budget=budget))

    def distance(self, space: GraphSpace | GridSpace | HexGridSpace | ContinuousSpace, start: object, goal: object) -> float:
        if isinstance(space, GraphSpace):
            route = space.route(str(start), str(goal))
            return sum(space.edges[a][b] for a, b in zip(route, route[1:]))
        if isinstance(space, HexGridSpace):
            return float(space.distance(cast(tuple[int, int], start), cast(tuple[int, int], goal)))
        if isinstance(space, GridSpace):
            a = cast(tuple[int, int], start)
            b = cast(tuple[int, int], goal)
            return float(abs(a[0] - b[0]) + abs(a[1] - b[1]))
        return dist(cast(tuple[float, ...], start), cast(tuple[float, ...], goal))

    def visible(self, space: GridSpace, start: tuple[int, int], goal: tuple[int, int]) -> bool:
        return space.line_of_sight(start, goal)

    def cover(self, space: GridSpace, start: tuple[int, int], goal: tuple[int, int]) -> int:
        return space.cover(start, goal)

    def occupants(self, space: GraphSpace | GridSpace | HexGridSpace, location: object) -> tuple[str, ...]:
        if isinstance(space, GraphSpace):
            return tuple(sorted(space.occupancy.get(str(location), set())))
        occupant = space.occupancy.get(cast(tuple[int, int], location))
        return () if occupant is None else (occupant,)
