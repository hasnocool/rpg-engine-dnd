# tests/test_studio_exchange.py
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rpg_engine_dnd.browser import BROWSER_HTML, ORIGINAL_BROWSER_HTML
from rpg_engine_dnd.studio import (
    StudioEditors,
    StudioItemEnvelope,
    StudioItemKind,
    StudioProject,
)
from rpg_engine_dnd.studio_browser import BROWSER_HTML as STUDIO_BROWSER_HTML


def test_studio_item_export_import_round_trip() -> None:
    editors = StudioEditors()
    raw = {
        "creature_id": "clockwork-heron",
        "name": "Clockwork Heron",
        "stats": {"armor": 14, "hp": 11},
        "tags": ["construct", "coastal"],
    }
    envelope = editors.export_item(StudioItemKind.CREATURE, "clockwork-heron", raw)

    assert envelope.schema_version == 1
    assert len(envelope.content_hash) == 64
    imported = editors.import_item(envelope)
    assert imported["creature_id"] == "clockwork-heron"
    assert imported["stats"] == {"armor": 14, "hp": 11}


def test_studio_item_rejects_tampering_and_identifier_mismatch() -> None:
    editors = StudioEditors()
    envelope = editors.export_item(
        StudioItemKind.SPELL,
        "shore-light",
        {
            "spell_id": "shore-light",
            "name": "Shore Light",
            "level": 0,
            "tags": ["light"],
        },
    )
    raw = envelope.model_dump(mode="json")
    raw["content"]["name"] = "Tampered"
    with pytest.raises(ValidationError, match="content hash mismatch"):
        StudioItemEnvelope.model_validate(raw)

    with pytest.raises(ValueError, match="must match"):
        editors.export_item(
            StudioItemKind.SPELL,
            "different-id",
            envelope.content,
        )


def test_project_import_collision_replace_and_export() -> None:
    editors = StudioEditors()
    first = editors.export_item(
        StudioItemKind.MAP,
        "coast",
        {"nodes": [{"id": "a"}], "edges": []},
    )
    second = editors.export_item(
        StudioItemKind.MAP,
        "coast",
        {"nodes": [{"id": "b"}], "edges": []},
    )
    project = StudioProject(project_id="p1", name="Portable")
    project.import_item(first)
    with pytest.raises(ValueError, match="already exists"):
        project.import_item(second)
    project.import_item(second, replace=True)

    exported = project.export_item(StudioItemKind.MAP, "coast")
    assert exported == second
    assert StudioProject.model_validate(project.model_dump(mode="json")) == project


def test_example_shattered_beacon_project_validates_all_items() -> None:
    path = Path(__file__).parents[1] / "examples" / "shattered-beacon" / "studio-project.json"
    project = StudioProject.model_validate(json.loads(path.read_text(encoding="utf-8")))
    items = [StudioItemEnvelope.model_validate(raw) for raw in project.document["items"]]

    assert project.project_id == "example-shattered-beacon"
    assert len(items) == 16
    assert {item.kind for item in items} >= {
        StudioItemKind.MAP,
        StudioItemKind.CREATURE,
        StudioItemKind.SPELL,
        StudioItemKind.QUEST,
        StudioItemKind.RULES,
        StudioItemKind.CAMPAIGN,
        StudioItemKind.RULE_GRAPH,
    }


def test_original_browser_is_restored_as_browser_navigation_view() -> None:
    for control_id in (
        "campaign",
        "owner",
        "create",
        "refresh",
        "entity",
        "name",
        "addEntity",
        "project",
        "saveProject",
        "snapshotProject",
        "map",
        "studio",
        "world",
    ):
        assert f'id="{control_id}"' in ORIGINAL_BROWSER_HTML

    assert "Save map project" in ORIGINAL_BROWSER_HTML
    assert "Click empty space to add nodes" in ORIGINAL_BROWSER_HTML
    assert 'id="libraryProject"' not in ORIGINAL_BROWSER_HTML
    assert 'id="mapItem"' not in ORIGINAL_BROWSER_HTML

    assert 'id="navBrowser"' in BROWSER_HTML
    assert 'id="navStudio"' in BROWSER_HTML
    assert 'title="Original RPG browser"' in BROWSER_HTML
    assert 'title="Creator Studio"' in BROWSER_HTML
    assert "#creator-studio" in BROWSER_HTML


def test_creator_studio_remains_intact_as_separate_navigation_view() -> None:
    for control_id in (
        "campaign",
        "owner",
        "create",
        "refresh",
        "entity",
        "name",
        "addEntity",
        "project",
        "mapItem",
        "saveProject",
        "snapshotProject",
        "exportMap",
        "importFile",
        "importItem",
        "map",
        "studio",
        "world",
    ):
        assert f'id="{control_id}"' in STUDIO_BROWSER_HTML

    assert 'id="libraryProject"' in STUDIO_BROWSER_HTML
    assert 'id="loadLibrary"' in STUDIO_BROWSER_HTML
    assert 'id="libraryItem"' in STUDIO_BROWSER_HTML
    assert 'id="loadItem"' in STUDIO_BROWSER_HTML
    assert 'id="itemEditor"' in STUDIO_BROWSER_HTML
    assert 'id="exportItem"' in STUDIO_BROWSER_HTML
    assert "The Shattered Beacon" in STUDIO_BROWSER_HTML
    assert "BUNDLED_PROJECTS" in STUDIO_BROWSER_HTML
    assert "Studio item hash verification failed" in STUDIO_BROWSER_HTML

    project_controls = STUDIO_BROWSER_HTML.index('id="snapshotProject"')
    content_library = STUDIO_BROWSER_HTML.index('<h3>Content library</h3>')
    portable_import = STUDIO_BROWSER_HTML.index('id="importFile"')
    assert project_controls < content_library < portable_import


def test_loading_bundled_content_does_not_persist_or_destroy_revisions() -> None:
    load_function = STUDIO_BROWSER_HTML.split("async function loadBundledProject(key)", 1)[1].split(
        "$('loadLibrary').onclick", 1
    )[0]

    assert "/v3/studio/projects" not in load_function
    assert "Use Save Studio project to persist changes" in load_function
