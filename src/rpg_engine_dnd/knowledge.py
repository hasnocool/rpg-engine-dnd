"""v2.3 per-actor perception and knowledge authority with scoped world projections."""

from __future__ import annotations

from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field

from .models import Entity, World


class KnowledgeFact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    value: object
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str | None = None
    tags: frozenset[str] = frozenset()
    expires_at_sequence: int | None = Field(default=None, ge=0)


class KnownEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    observed_at_sequence: int = Field(ge=0)
    remembered_components: dict[str, dict[str, object]] = Field(default_factory=dict)
    facts: dict[str, KnowledgeFact] = Field(default_factory=dict)


class ActorKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str
    known_entities: dict[str, KnownEntity] = Field(default_factory=dict)


class KnowledgeView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    viewer_id: str | None
    sequence: int = Field(ge=0)
    entities: dict[str, dict[str, dict[str, object]]]
    omniscient: bool = False


class KnowledgeAuthority:
    def __init__(self, *, public_components: set[str] | None = None) -> None:
        self.public_components = set(public_components or {"identity", "position", "appearance"})
        self._knowledge: dict[str, ActorKnowledge] = {}

    def ingest_perception(self, actor_id: str, entity: Entity, *, sequence: int) -> KnownEntity:
        knowledge = self._knowledge.setdefault(actor_id, ActorKnowledge(actor_id=actor_id))
        public = {
            name: deepcopy(value)
            for name, value in entity.components.items()
            if name in self.public_components or entity.entity_id == actor_id
        }
        remembered = KnownEntity(
            entity_id=entity.entity_id,
            observed_at_sequence=sequence,
            remembered_components=public,
        )
        knowledge.known_entities[entity.entity_id] = remembered
        return remembered

    def add_fact(self, actor_id: str, entity_id: str, fact: KnowledgeFact, *, sequence: int) -> None:
        knowledge = self._knowledge.setdefault(actor_id, ActorKnowledge(actor_id=actor_id))
        known = knowledge.known_entities.setdefault(
            entity_id,
            KnownEntity(entity_id=entity_id, observed_at_sequence=sequence),
        )
        known.facts[fact.key] = fact

    def actor_view(self, world: World, actor_id: str, *, sequence: int | None = None) -> KnowledgeView:
        current_sequence = world.revision if sequence is None else sequence
        knowledge = self._knowledge.setdefault(actor_id, ActorKnowledge(actor_id=actor_id))
        entities: dict[str, dict[str, dict[str, object]]] = {}
        for entity_id, known in knowledge.known_entities.items():
            remembered = deepcopy(known.remembered_components)
            if entity_id == actor_id and entity_id in world.entities:
                remembered = deepcopy(world.entities[entity_id].components)
            entities[entity_id] = remembered
        return KnowledgeView(viewer_id=actor_id, sequence=current_sequence, entities=entities)

    def owner_view(self, world: World, owner_id: str, owned_actor_ids: set[str]) -> KnowledgeView:
        merged: dict[str, dict[str, dict[str, object]]] = {}
        for actor_id in sorted(owned_actor_ids):
            merged.update(self.actor_view(world, actor_id).entities)
        return KnowledgeView(viewer_id=owner_id, sequence=world.revision, entities=merged)

    def omniscient_view(self, world: World, owner_id: str) -> KnowledgeView:
        entities = {entity_id: deepcopy(entity.components) for entity_id, entity in sorted(world.entities.items())}
        return KnowledgeView(viewer_id=owner_id, sequence=world.revision, entities=entities, omniscient=True)

    def spectator_view(self, world: World) -> KnowledgeView:
        shell: dict[str, dict[str, dict[str, object]]] = {}
        for entity_id, entity in sorted(world.entities.items()):
            public = {name: deepcopy(value) for name, value in entity.components.items() if name in self.public_components}
            if public:
                shell[entity_id] = public
        return KnowledgeView(viewer_id=None, sequence=world.revision, entities=shell)
