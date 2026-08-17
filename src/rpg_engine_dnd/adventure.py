"""v0.3 graph exploration, dialogue, quests, NPC profiles, and shops."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MapNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    discoveries: tuple[str, ...] = ()


class MapEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str
    target: str
    cost: float = Field(default=1.0, gt=0)
    bidirectional: bool = True


class GraphMap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: dict[str, MapNode] = Field(default_factory=dict)
    edges: list[MapEdge] = Field(default_factory=list)
    discovered_by_actor: dict[str, set[str]] = Field(default_factory=dict)

    def add_node(self, node: MapNode) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, edge: MapEdge) -> None:
        if edge.source not in self.nodes or edge.target not in self.nodes:
            raise KeyError("both edge endpoints must exist")
        self.edges.append(edge)

    def neighbors(self, node_id: str) -> list[tuple[str, float]]:
        result: list[tuple[str, float]] = []
        for edge in self.edges:
            if edge.source == node_id:
                result.append((edge.target, edge.cost))
            elif edge.bidirectional and edge.target == node_id:
                result.append((edge.source, edge.cost))
        return sorted(result)

    def explore(self, actor_id: str, node_id: str) -> tuple[str, ...]:
        node = self.nodes[node_id]
        seen = self.discovered_by_actor.setdefault(actor_id, set())
        first_visit = node_id not in seen
        seen.add(node_id)
        return node.discoveries if first_visit else ()


class DialogueChoice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str
    next_node: str | None = None
    requires: dict[str, object] = Field(default_factory=dict)
    emits: tuple[str, ...] = ()


class DialogueNode(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: str
    speaker: str
    text: str
    choices: tuple[DialogueChoice, ...] = ()


class DialogueGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_node: str
    nodes: dict[str, DialogueNode]

    @staticmethod
    def _requirements_met(requirements: dict[str, object], facts: dict[str, object]) -> bool:
        return all(facts.get(key) == expected for key, expected in requirements.items())

    def available_choices(self, node_id: str, facts: dict[str, object]) -> list[DialogueChoice]:
        return [
            choice
            for choice in self.nodes[node_id].choices
            if self._requirements_met(choice.requires, facts)
        ]


class QuestObjective(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_id: str
    event_kind: str
    target: int = Field(default=1, ge=1)
    progress: int = Field(default=0, ge=0)

    @property
    def complete(self) -> bool:
        return self.progress >= self.target


class Quest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quest_id: str
    title: str
    objectives: list[QuestObjective] = Field(default_factory=list)
    completed: bool = False

    def ingest_event(self, event_kind: str) -> bool:
        for index, objective in enumerate(self.objectives):
            if objective.event_kind == event_kind and not objective.complete:
                self.objectives[index] = objective.model_copy(
                    update={"progress": min(objective.target, objective.progress + 1)}
                )
        self.completed = bool(self.objectives) and all(obj.complete for obj in self.objectives)
        return self.completed


class NPCProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    npc_id: str
    name: str
    disposition: int = Field(default=0, ge=-100, le=100)
    tags: set[str] = Field(default_factory=set)
    facts: dict[str, object] = Field(default_factory=dict)


class ShopStock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    price: int = Field(ge=0)
    quantity: int = Field(ge=0)


class Shop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop_id: str
    stock: dict[str, ShopStock] = Field(default_factory=dict)

    def buy(self, item_id: str, *, quantity: int = 1) -> int:
        if quantity < 1:
            raise ValueError("quantity must be positive")
        stock = self.stock[item_id]
        if stock.quantity < quantity:
            raise ValueError("insufficient stock")
        self.stock[item_id] = stock.model_copy(update={"quantity": stock.quantity - quantity})
        return stock.price * quantity

    def sell_to_shop(self, item_id: str, *, unit_price: int, quantity: int = 1) -> int:
        if quantity < 1 or unit_price < 0:
            raise ValueError("invalid quantity or price")
        current = self.stock.get(item_id)
        existing = 0 if current is None else current.quantity
        self.stock[item_id] = ShopStock(item_id=item_id, price=unit_price, quantity=existing + quantity)
        return unit_price * quantity
