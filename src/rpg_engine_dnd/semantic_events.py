"""Semantic domain events, journal segmentation, snapshots, and compaction."""

from __future__ import annotations

from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_hash
from .event_sourcing import EventJournal, JournalEntry


class DomainEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(ge=1)
    event_id: str
    kind: str
    actor_id: str | None = None
    entity_id: str | None = None
    data: dict[str, object] = Field(default_factory=dict)
    caused_by: str | None = None


class JournalSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(ge=0)
    state: dict[str, object]
    state_hash: str
    head_hash: str


class JournalSegment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    start_sequence: int = Field(ge=1)
    end_sequence: int = Field(ge=1)
    entry_hashes: tuple[str, ...]
    segment_hash: str


class SemanticEventJournal:
    """Pairs human-readable domain events with deterministic structural patches."""

    def __init__(self, initial_state: dict[str, object] | None = None, *, snapshot_interval: int = 500) -> None:
        if snapshot_interval < 1:
            raise ValueError("snapshot_interval must be positive")
        self.journal = EventJournal(initial_state)
        self.domain_events: list[DomainEvent] = []
        self.snapshots: list[JournalSnapshot] = []
        self.snapshot_interval = snapshot_interval

    def append(
        self,
        *,
        command_id: str,
        event_kind: str,
        before: dict[str, object],
        after: dict[str, object],
        actor_id: str | None = None,
        entity_id: str | None = None,
        data: dict[str, object] | None = None,
    ) -> tuple[JournalEntry, DomainEvent]:
        entry = self.journal.append(command_id=command_id, event_kind=event_kind, before=before, after=after)
        domain = DomainEvent(
            sequence=entry.sequence,
            event_id=f"{entry.sequence}:{entry.entry_hash[:16]}",
            kind=event_kind,
            actor_id=actor_id,
            entity_id=entity_id,
            data={} if data is None else deepcopy(data),
            caused_by=command_id,
        )
        if len(self.domain_events) < entry.sequence:
            self.domain_events.append(domain)
        else:
            self.domain_events[entry.sequence - 1] = domain
        if entry.sequence % self.snapshot_interval == 0:
            self.create_snapshot(entry.sequence)
        return entry, domain

    def create_snapshot(self, sequence: int | None = None) -> JournalSnapshot:
        resolved = len(self.journal.entries) if sequence is None else sequence
        state = self.journal.replay(through_sequence=resolved)
        head_hash = (
            self.journal.entries[resolved - 1].entry_hash
            if resolved
            else canonical_hash({"journal": "root"})
        )
        snapshot = JournalSnapshot(
            sequence=resolved,
            state=deepcopy(state),
            state_hash=canonical_hash(state),
            head_hash=head_hash,
        )
        self.snapshots.append(snapshot)
        return snapshot

    def segments(self, *, size: int = 1000) -> tuple[JournalSegment, ...]:
        if size < 1:
            raise ValueError("segment size must be positive")
        result: list[JournalSegment] = []
        entries = self.journal.entries
        for offset in range(0, len(entries), size):
            chunk = entries[offset : offset + size]
            if not chunk:
                continue
            hashes = tuple(entry.entry_hash for entry in chunk)
            result.append(
                JournalSegment(
                    start_sequence=chunk[0].sequence,
                    end_sequence=chunk[-1].sequence,
                    entry_hashes=hashes,
                    segment_hash=canonical_hash({"hashes": hashes}),
                )
            )
        return tuple(result)

    def verify(self) -> bool:
        state = self.journal.replay()
        if self.snapshots:
            latest = self.snapshots[-1]
            checkpoint = self.journal.replay(through_sequence=latest.sequence)
            if canonical_hash(checkpoint) != latest.state_hash:
                return False
        return canonical_hash(state) == canonical_hash(self.journal.replay())


class SemanticJournalPersistence:
    """Non-blocking persistence bridge using the shared async JSON store contract."""

    def __init__(self, store: object, campaign_id: str) -> None:
        self.store = store
        self.campaign_id = campaign_id

    async def save_snapshot(self, snapshot: JournalSnapshot) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json(
            f"journal-snapshot:{self.campaign_id}",
            f"{snapshot.sequence:020d}",
            snapshot.model_dump(mode="json"),
        )

    async def save_domain_event(self, event: DomainEvent) -> None:
        put_json = getattr(self.store, "put_json")
        await put_json(
            f"domain-event:{self.campaign_id}",
            f"{event.sequence:020d}",
            event.model_dump(mode="json"),
        )
