"""Non-blocking async SQLite persistence for world snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from .models import World

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS campaign_snapshots (
    campaign_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (campaign_id, revision)
);
CREATE INDEX IF NOT EXISTS ix_campaign_snapshots_latest
    ON campaign_snapshots (campaign_id, revision DESC);
"""


class AsyncSQLiteStore:
    """Async SQLite snapshot store using aiosqlite's worker-thread boundary."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def save_snapshot(self, campaign_id: str, world: World) -> None:
        if not campaign_id:
            raise ValueError("campaign_id must not be empty")
        payload = json.dumps(world.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO campaign_snapshots (campaign_id, revision, snapshot_json) VALUES (?, ?, ?) ON CONFLICT(campaign_id, revision) DO UPDATE SET snapshot_json = excluded.snapshot_json",
                (campaign_id, world.revision, payload),
            )
            await db.commit()

    async def load_latest_snapshot(self, campaign_id: str) -> World | None:
        if not campaign_id:
            raise ValueError("campaign_id must not be empty")
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT snapshot_json FROM campaign_snapshots WHERE campaign_id = ? ORDER BY revision DESC LIMIT 1", (campaign_id,))
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        raw: Any = json.loads(row[0])
        return World.model_validate(raw)
