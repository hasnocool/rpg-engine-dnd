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
    """Async persistence boundary.

    `aiosqlite` executes SQLite operations on its worker thread, avoiding synchronous
    database calls on the caller's event-loop thread.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def save_snapshot(self, campaign_id: str, world: World) -> None:
        if not campaign_id:
            raise ValueError("campaign_id must not be empty")
        payload = json.dumps(
            world.canonical_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO campaign_snapshots (campaign_id, revision, snapshot_json)
                VALUES (?, ?, ?)
                ON CONFLICT(campaign_id, revision)
                DO UPDATE SET snapshot_json = excluded.snapshot_json
                """,
                (campaign_id, world.revision, payload),
            )
            await db.commit()

    async def load_latest_snapshot(self, campaign_id: str) -> World | None:
        if not campaign_id:
            raise ValueError("campaign_id must not be empty")
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT snapshot_json
                FROM campaign_snapshots
                WHERE campaign_id = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (campaign_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()

        if row is None:
            return None
        raw: Any = json.loads(row[0])
        return World.model_validate(raw)

_PLATFORM_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_json (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(namespace, key)
);
CREATE INDEX IF NOT EXISTS ix_platform_json_namespace
    ON platform_json(namespace, key);
"""


class AsyncSQLitePlatformStore:
    """Generic async JSON persistence shared by hosting, distribution, and sharding."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_PLATFORM_SCHEMA)
            await db.commit()

    async def put_json(self, namespace: str, key: str, value: dict[str, object]) -> None:
        if not namespace or not key:
            raise ValueError("namespace and key must not be empty")
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO platform_json(namespace, key, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(namespace, key)
                DO UPDATE SET payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP
                """,
                (namespace, key, payload),
            )
            await db.commit()

    async def compare_and_set_json(
        self,
        namespace: str,
        key: str,
        expected: dict[str, object] | None,
        value: dict[str, object],
    ) -> bool:
        if not namespace or not key:
            raise ValueError("namespace and key must not be empty")
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                "SELECT payload_json FROM platform_json WHERE namespace=? AND key=?",
                (namespace, key),
            )
            row = await cursor.fetchone()
            await cursor.close()
            current: dict[str, object] | None = None
            if row is not None:
                raw: Any = json.loads(row[0])
                if not isinstance(raw, dict):
                    await db.rollback()
                    raise ValueError("stored platform JSON must be an object")
                current = raw
            if current != expected:
                await db.rollback()
                return False
            await db.execute(
                """
                INSERT INTO platform_json(namespace, key, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(namespace, key)
                DO UPDATE SET payload_json=excluded.payload_json, updated_at=CURRENT_TIMESTAMP
                """,
                (namespace, key, payload),
            )
            await db.commit()
            return True

    async def get_json(self, namespace: str, key: str) -> dict[str, object] | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT payload_json FROM platform_json WHERE namespace=? AND key=?",
                (namespace, key),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        value: Any = json.loads(row[0])
        if not isinstance(value, dict):
            raise ValueError("stored platform JSON must be an object")
        return value

    async def list_json(self, namespace: str) -> dict[str, dict[str, object]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT key, payload_json FROM platform_json WHERE namespace=? ORDER BY key",
                (namespace,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        result: dict[str, dict[str, object]] = {}
        for key, payload in rows:
            value: Any = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("stored platform JSON must be an object")
            result[str(key)] = value
        return result
