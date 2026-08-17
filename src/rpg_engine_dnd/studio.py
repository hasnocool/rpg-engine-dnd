"""v1.8 Creator Studio project/revision model and structured editors."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash
from .creator import (
    CampaignTemplate,
    ContentValidator,
    CreatureDocument,
    MapDocument,
    QuestDocument,
    RulesKnobs,
    SpellDocument,
)


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
