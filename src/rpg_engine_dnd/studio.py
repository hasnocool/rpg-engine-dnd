"""v1.8 Creator Studio project/revision model, typed editors, and import/export exchange."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import canonical_hash
from .compiler import RuleCompiler, RuleDocument
from .creator import (
    CampaignTemplate,
    ContentValidator,
    CreatureDocument,
    MapDocument,
    QuestDocument,
    RulesKnobs,
    SpellDocument,
)


class StudioItemKind(StrEnum):
    MAP = "map"
    CREATURE = "creature"
    SPELL = "spell"
    QUEST = "quest"
    RULES = "rules"
    CAMPAIGN = "campaign"
    RULE_GRAPH = "rule_graph"


class StudioItemEnvelope(BaseModel):
    """Portable, hash-verified Creator Studio item exchange format."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    kind: StudioItemKind
    item_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    content: dict[str, object]

    @model_validator(mode="after")
    def verify_hash(self) -> "StudioItemEnvelope":
        if canonical_hash(self.content) != self.content_hash:
            raise ValueError("studio item content hash mismatch")
        return self


class StudioRevision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    revision_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str
    document: dict[str, object]


class StudioProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    name: str
    document: dict[str, object] = Field(default_factory=dict)
    revisions: list[StudioRevision] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_portable_items(self) -> "StudioProject":
        raw_items = self.document.get("items")
        if raw_items is None:
            return self
        if not isinstance(raw_items, list):
            raise ValueError("studio project document.items must be a list")
        editors = StudioEditors()
        for raw in raw_items:
            envelope = StudioItemEnvelope.model_validate(raw)
            editors.import_item(envelope)
        return self

    def snapshot(self) -> StudioRevision:
        document = deepcopy(self.document)
        revision = StudioRevision(
            revision_id=f"{self.project_id}:r{len(self.revisions) + 1}",
            content_hash=canonical_hash(document),
            document=document,
        )
        self.revisions.append(revision)
        return revision

    def restore_as_new_revision(self, revision_id: str) -> StudioRevision:
        source = next(revision for revision in self.revisions if revision.revision_id == revision_id)
        self.document = deepcopy(source.document)
        return self.snapshot()

    def import_item(self, envelope: StudioItemEnvelope, *, replace: bool = False) -> None:
        StudioEditors().import_item(envelope)
        raw_items = self.document.setdefault("items", [])
        if not isinstance(raw_items, list):
            raise ValueError("studio project document.items must be a list")
        items = [StudioItemEnvelope.model_validate(raw) for raw in raw_items]
        matching = [item for item in items if item.kind == envelope.kind and item.item_id == envelope.item_id]
        if matching and not replace:
            raise ValueError(f"studio item already exists: {envelope.kind.value}/{envelope.item_id}")
        retained = [
            item
            for item in items
            if not (item.kind == envelope.kind and item.item_id == envelope.item_id)
        ]
        retained.append(envelope)
        retained.sort(key=lambda item: (item.kind.value, item.item_id))
        self.document["items"] = [item.model_dump(mode="json") for item in retained]

    def export_item(self, kind: StudioItemKind, item_id: str) -> StudioItemEnvelope:
        raw_items = self.document.get("items", [])
        if not isinstance(raw_items, list):
            raise ValueError("studio project document.items must be a list")
        for raw in raw_items:
            envelope = StudioItemEnvelope.model_validate(raw)
            if envelope.kind == kind and envelope.item_id == item_id:
                return envelope
        raise KeyError(f"studio item not found: {kind.value}/{item_id}")


class StudioEditors:
    """Structured editor facade; visual frontends can bind to these typed documents."""

    def __init__(self, validator: ContentValidator | None = None) -> None:
        self.validator = validator or ContentValidator()

    def map_document(self, raw: dict[str, object]) -> MapDocument:
        return MapDocument.model_validate(raw)

    def creature_document(self, raw: dict[str, object]) -> CreatureDocument:
        return CreatureDocument.model_validate(raw)

    def spell_document(self, raw: dict[str, object]) -> SpellDocument:
        return SpellDocument.model_validate(raw)

    def quest_document(self, raw: dict[str, object]) -> QuestDocument:
        return QuestDocument.model_validate(raw)

    def rules_document(self, raw: dict[str, object]) -> RulesKnobs:
        rules = RulesKnobs.model_validate(raw)
        errors = self.validator.validate_rules(rules)
        if errors:
            raise ValueError("; ".join(errors))
        return rules

    def campaign_template(self, raw: dict[str, object]) -> CampaignTemplate:
        template = CampaignTemplate.model_validate(raw)
        errors = self.validator.validate_template(template)
        if errors:
            raise ValueError("; ".join(errors))
        return template

    def rule_graph(self, raw: dict[str, object]) -> RuleDocument:
        document = RuleDocument.model_validate(raw)
        RuleCompiler().compile(document)
        return document

    def _normalize(self, kind: StudioItemKind, raw: dict[str, object]) -> dict[str, object]:
        if kind == StudioItemKind.MAP:
            model = self.map_document(raw)
        elif kind == StudioItemKind.CREATURE:
            model = self.creature_document(raw)
        elif kind == StudioItemKind.SPELL:
            model = self.spell_document(raw)
        elif kind == StudioItemKind.QUEST:
            model = self.quest_document(raw)
        elif kind == StudioItemKind.RULES:
            model = self.rules_document(raw)
        elif kind == StudioItemKind.CAMPAIGN:
            model = self.campaign_template(raw)
        elif kind == StudioItemKind.RULE_GRAPH:
            model = self.rule_graph(raw)
        else:  # pragma: no cover - StrEnum exhaustiveness guard
            raise ValueError(f"unsupported studio item kind: {kind}")
        return model.model_dump(mode="json")

    @staticmethod
    def _assert_item_id(kind: StudioItemKind, item_id: str, content: dict[str, object]) -> None:
        field_by_kind = {
            StudioItemKind.CREATURE: "creature_id",
            StudioItemKind.SPELL: "spell_id",
            StudioItemKind.QUEST: "quest_id",
            StudioItemKind.CAMPAIGN: "template_id",
            StudioItemKind.RULE_GRAPH: "rule_id",
        }
        field = field_by_kind.get(kind)
        if field is not None and str(content.get(field, "")) != item_id:
            raise ValueError(f"studio item id must match content.{field}")

    def export_item(self, kind: StudioItemKind, item_id: str, raw: dict[str, object]) -> StudioItemEnvelope:
        content = self._normalize(kind, raw)
        self._assert_item_id(kind, item_id, content)
        return StudioItemEnvelope(
            kind=kind,
            item_id=item_id,
            content_hash=canonical_hash(content),
            content=content,
        )

    def import_item(self, envelope: StudioItemEnvelope) -> dict[str, object]:
        content = self._normalize(envelope.kind, envelope.content)
        self._assert_item_id(envelope.kind, envelope.item_id, content)
        return content


class StudioRepository:
    """Async persistence adapter for typed Studio projects and immutable revisions."""

    def __init__(self, store: object) -> None:
        self.store = store

    async def save(self, project: StudioProject) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json("studio:project", project.project_id, project.model_dump(mode="json"))
        for revision in project.revisions:
            await put_json("studio:revision", revision.revision_id, revision.model_dump(mode="json"))

    async def load(self, project_id: str) -> StudioProject | None:
        get_json = getattr(self.store, "get_json")
        value = await get_json("studio:project", project_id)
        return None if value is None else StudioProject.model_validate(value)
