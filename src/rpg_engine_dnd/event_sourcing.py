"""v1.3 deterministic patches, hash-chained journals, replay, rewind, branching, and idempotency."""

from __future__ import annotations

from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash


JSONValue = object


def make_patch(before: object, after: object) -> object:
    """Create a deterministic JSON merge-style patch."""
    if before == after:
        return {}
    if isinstance(before, dict) and isinstance(after, dict):
        patch: dict[str, object] = {}
        for key in sorted(set(before) | set(after)):
            if key not in after:
                patch[key] = None
            elif key not in before:
                patch[key] = deepcopy(after[key])
            else:
                nested = make_patch(before[key], after[key])
                if nested != {}:
                    patch[key] = nested
        return patch
    return deepcopy(after)


def apply_patch(state: object, patch: object) -> object:
    if not isinstance(patch, dict):
        return deepcopy(patch)
    if not isinstance(state, dict):
        state = {}
    result = deepcopy(state)
    assert isinstance(result, dict)
    for key in sorted(patch):
        value = patch[key]
        if value is None:
            result.pop(key, None)
        else:
            result[key] = apply_patch(result.get(key), value)
    return result


class JournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(ge=1)
    command_id: str
    event_kind: str
    patch: object
    previous_hash: str
    before_hash: str
    after_hash: str
    entry_hash: str


class EventJournal:
    def __init__(self, initial_state: dict[str, object] | None = None) -> None:
        self.initial_state = deepcopy(initial_state or {})
        self.entries: list[JournalEntry] = []
        self._command_ids: dict[str, int] = {}

    @property
    def head_hash(self) -> str:
        return self.entries[-1].entry_hash if self.entries else canonical_hash({"journal": "root"})

    def append(self, *, command_id: str, event_kind: str, before: dict[str, object], after: dict[str, object]) -> JournalEntry:
        if command_id in self._command_ids:
            return self.entries[self._command_ids[command_id] - 1]
        patch = make_patch(before, after)
        sequence = len(self.entries) + 1
        previous_hash = self.head_hash
        material = {
            "sequence": sequence,
            "command_id": command_id,
            "event_kind": event_kind,
            "patch": patch,
            "previous_hash": previous_hash,
            "before_hash": canonical_hash(before),
            "after_hash": canonical_hash(after),
        }
        entry = JournalEntry(**material, entry_hash=canonical_hash(material))
        self.entries.append(entry)
        self._command_ids[command_id] = sequence
        return entry

    def replay(self, *, through_sequence: int | None = None) -> dict[str, object]:
        state: object = deepcopy(self.initial_state)
        limit = len(self.entries) if through_sequence is None else through_sequence
        if limit < 0 or limit > len(self.entries):
            raise ValueError("invalid replay sequence")
        previous_hash = canonical_hash({"journal": "root"})
        for entry in self.entries[:limit]:
            if entry.previous_hash != previous_hash:
                raise ValueError("journal hash chain broken")
            if canonical_hash(state) != entry.before_hash:
                raise ValueError("journal before-state hash mismatch")
            state = apply_patch(state, entry.patch)
            if canonical_hash(state) != entry.after_hash:
                raise ValueError("journal after-state hash mismatch")
            material = entry.model_dump(mode="json", exclude={"entry_hash"})
            if canonical_hash(material) != entry.entry_hash:
                raise ValueError("journal entry hash mismatch")
            previous_hash = entry.entry_hash
        if not isinstance(state, dict):
            raise ValueError("journal state must remain an object")
        return state

    def rewind(self, sequence: int) -> dict[str, object]:
        return self.replay(through_sequence=sequence)

    def branch(self, sequence: int) -> "EventJournal":
        branched = EventJournal(self.initial_state)
        branched.entries = [entry.model_copy(deep=True) for entry in self.entries[:sequence]]
        branched._command_ids = {entry.command_id: entry.sequence for entry in branched.entries}
        return branched

    def verify_live_state(self, state: dict[str, object]) -> bool:
        return canonical_hash(self.replay()) == canonical_hash(state)


class JournalPersistenceBridge:
    """Persist immutable journal entries through the shared async JSON contract."""

    def __init__(self, store: object, campaign_id: str) -> None:
        self.store = store
        self.campaign_id = campaign_id

    async def append(self, entry: JournalEntry) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json(
            f"journal:{self.campaign_id}",
            f"{entry.sequence:020d}",
            entry.model_dump(mode="json"),
        )

    async def load(self) -> list[JournalEntry]:
        list_json = getattr(self.store, "list_json")
        rows = await list_json(f"journal:{self.campaign_id}")
        return [JournalEntry.model_validate(rows[key]) for key in sorted(rows)]
