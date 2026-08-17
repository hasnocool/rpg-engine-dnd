from pathlib import Path

import pytest

from rpg_engine_dnd import AsyncSQLiteStore, CreateEntity, SimulationEngine


@pytest.mark.asyncio
async def test_snapshot_round_trip(tmp_path: Path) -> None:
    store = AsyncSQLiteStore(tmp_path / "campaign.sqlite3")
    await store.initialize()
    engine = SimulationEngine(seed=42)
    engine.handle(CreateEntity(command_id="create", entity_id="hero", components={"hp": {"current": 12, "maximum": 12}}))
    await store.save_snapshot("demo", engine.world)
    loaded = await store.load_latest_snapshot("demo")
    assert loaded is not None
    assert loaded == engine.world
