"""v1.4 authoritative graph/grid/continuous spaces, pathfinding, LOS, cover, and terrain."""

from __future__ import annotations

import heapq
import math
from pydantic import BaseModel, ConfigDict, Field


class GraphSpace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capacities: dict[str, int] = Field(default_factory=dict)
    edges: dict[str, dict[str, float]] = Field(default_factory=dict)
    occupancy: dict[str, set[str]] = Field(default_factory=dict)

    def connect(self, source: str, target: str, *, cost: float = 1.0, bidirectional: bool = True) -> None:
        if cost <= 0:
            raise ValueError("edge cost must be positive")
        self.edges.setdefault(source, {})[target] = cost
        if bidirectional:
            self.edges.setdefault(target, {})[source] = cost

    def route(self, source: str, target: str) -> list[str]:
        frontier: list[tuple[float, str]] = [(0.0, source)]
        cost = {source: 0.0}
        parent: dict[str, str | None] = {source: None}
        while frontier:
            current_cost, current = heapq.heappop(frontier)
            if current == target:
                break
            for neighbor, edge_cost in sorted(self.edges.get(current, {}).items()):
                new_cost = current_cost + edge_cost
                if neighbor not in cost or new_cost < cost[neighbor]:
                    cost[neighbor] = new_cost
                    parent[neighbor] = current
                    heapq.heappush(frontier, (new_cost, neighbor))
        if target not in parent:
            raise ValueError("no route")
        result: list[str] = []
        cursor: str | None = target
        while cursor is not None:
            result.append(cursor)
            cursor = parent[cursor]
        return list(reversed(result))

    def enter(self, node: str, entity_id: str) -> None:
        occupants = self.occupancy.setdefault(node, set())
        capacity = self.capacities.get(node)
        if capacity is not None and len(occupants) >= capacity and entity_id not in occupants:
            raise ValueError("space capacity exceeded")
        occupants.add(entity_id)


class GridCell(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    x: int
    y: int
    terrain: str = "normal"
    movement_cost: float = Field(default=1.0, gt=0)
    blocks_movement: bool = False
    blocks_los: bool = False
    cover: int = Field(default=0, ge=0, le=3)


class GridSpace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    cells: dict[tuple[int, int], GridCell] = Field(default_factory=dict)
    occupancy: dict[tuple[int, int], str] = Field(default_factory=dict)

    def cell(self, x: int, y: int) -> GridCell:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError("grid coordinate out of bounds")
        return self.cells.get((x, y), GridCell(x=x, y=y))

    def occupy(self, entity_id: str, coordinate: tuple[int, int]) -> None:
        cell = self.cell(*coordinate)
        if cell.blocks_movement:
            raise ValueError("cell blocks movement")
        current = self.occupancy.get(coordinate)
        if current is not None and current != entity_id:
            raise ValueError("cell occupied")
        for key, value in list(self.occupancy.items()):
            if value == entity_id and key != coordinate:
                del self.occupancy[key]
        self.occupancy[coordinate] = entity_id

    def path(self, start: tuple[int, int], goal: tuple[int, int], *, budget: float | None = None) -> list[tuple[int, int]]:
        frontier: list[tuple[float, float, tuple[int, int]]] = [(0.0, 0.0, start)]
        cost = {start: 0.0}
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        while frontier:
            _, current_cost, current = heapq.heappop(frontier)
            if current == goal:
                break
            x, y = current
            for neighbor in ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1)):
                try:
                    cell = self.cell(*neighbor)
                except ValueError:
                    continue
                if cell.blocks_movement or (neighbor in self.occupancy and neighbor != goal):
                    continue
                new_cost = current_cost + cell.movement_cost
                if budget is not None and new_cost > budget:
                    continue
                if neighbor not in cost or new_cost < cost[neighbor]:
                    cost[neighbor] = new_cost
                    parent[neighbor] = current
                    heuristic = abs(goal[0] - neighbor[0]) + abs(goal[1] - neighbor[1])
                    heapq.heappush(frontier, (new_cost + heuristic, new_cost, neighbor))
        if goal not in parent:
            raise ValueError("no path within authority constraints")
        result: list[tuple[int, int]] = []
        cursor: tuple[int, int] | None = goal
        while cursor is not None:
            result.append(cursor)
            cursor = parent[cursor]
        return list(reversed(result))

    @staticmethod
    def _line(start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
        x0, y0 = start
        x1, y1 = goal
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        error = dx + dy
        points: list[tuple[int, int]] = []
        while True:
            points.append((x0, y0))
            if (x0, y0) == (x1, y1):
                return points
            doubled = 2 * error
            if doubled >= dy:
                error += dy
                x0 += sx
            if doubled <= dx:
                error += dx
                y0 += sy

    def line_of_sight(self, start: tuple[int, int], goal: tuple[int, int]) -> bool:
        points = self._line(start, goal)
        return all(not self.cell(*point).blocks_los for point in points[1:-1])

    def cover(self, start: tuple[int, int], goal: tuple[int, int]) -> int:
        points = self._line(start, goal)
        return max((self.cell(*point).cover for point in points[1:-1]), default=0)


class ContinuousSpace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimensions: int = Field(default=2, ge=2, le=3)
    minimum: tuple[float, ...]
    maximum: tuple[float, ...]
    positions: dict[str, tuple[float, ...]] = Field(default_factory=dict)
    radii: dict[str, float] = Field(default_factory=dict)

    def _validate_point(self, point: tuple[float, ...]) -> None:
        if len(point) != self.dimensions:
            raise ValueError("point dimensionality mismatch")
        if any(value < low or value > high for value, low, high in zip(point, self.minimum, self.maximum, strict=True)):
            raise ValueError("point out of bounds")

    def move(self, entity_id: str, point: tuple[float, ...], *, movement_budget: float | None = None) -> None:
        self._validate_point(point)
        previous = self.positions.get(entity_id)
        if previous is not None and movement_budget is not None and math.dist(previous, point) > movement_budget:
            raise ValueError("movement budget exceeded")
        radius = self.radii.get(entity_id, 0.0)
        for other_id, other in self.positions.items():
            if other_id == entity_id:
                continue
            if math.dist(other, point) < radius + self.radii.get(other_id, 0.0):
                raise ValueError("collision")
        self.positions[entity_id] = point
