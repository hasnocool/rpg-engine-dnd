# tests/test_api_v3.py
from fastapi.testclient import TestClient

from rpg_engine_dnd.api import create_app


OWNER = {"x-owner-id": "gm"}


def _create_campaign_and_actor(client: TestClient) -> None:
    response = client.post(
        "/v3/campaigns",
        json={"campaign_id": "c1", "seed": "api-seed", "owner_id": "gm"},
    )
    assert response.status_code == 200
    response = client.post(
        "/v3/campaigns/c1/commands",
        headers=OWNER,
        json={
            "kind": "entity.create",
            "command_id": "c1:create:hero",
            "entity_id": "hero",
            "components": {
                "identity": {"name": "Aster"},
                "inventory": {"gold": 17, "secret": "hidden"},
            },
        },
    )
    assert response.status_code == 200
    response = client.post(
        "/v3/campaigns/c1/ownership",
        headers=OWNER,
        json={"user_id": "player-1", "actor_id": "hero"},
    )
    assert response.status_code == 200


def test_knowledge_scoped_api_and_lifecycle() -> None:
    with TestClient(create_app()) as client:
        _create_campaign_and_actor(client)

        spectator = client.get("/v3/campaigns/c1").json()
        assert spectator["omniscient"] is False
        assert spectator["entities"]["hero"] == {"identity": {"name": "Aster"}}

        player = client.get(
            "/v3/campaigns/c1?actor_id=hero",
            headers={"x-user-id": "player-1"},
        ).json()
        assert player["entities"]["hero"]["inventory"]["gold"] == 17

        owner = client.get("/v3/campaigns/c1", headers=OWNER).json()
        assert owner["omniscient"] is True
        assert owner["entities"]["hero"]["inventory"]["secret"] == "hidden"

        lifecycle = client.post(
            "/v3/campaigns/c1/actors/hero/lifecycle",
            headers=OWNER,
            json={
                "command_id": "life:1",
                "build": {
                    "character_id": "hero",
                    "name": "Aster",
                    "ability_scores": {"strength": 14},
                    "class_levels": {"fighter": 1},
                },
                "resources": {
                    "focus": {
                        "resource_id": "focus",
                        "current": 0,
                        "maximum": 2,
                        "recover_short": 1,
                        "recover_long": 2,
                    }
                },
            },
        )
        assert lifecycle.status_code == 200
        assert lifecycle.json()["lifecycle"]["progression"]["level"] == 1

        leveled = client.post(
            "/v3/campaigns/c1/actors/hero/level-up",
            headers=OWNER,
            json={
                "command_id": "life:2",
                "to_level": 2,
                "hit_point_gain": 7,
                "features": ["second-feature"],
                "ability_points": 1,
            },
        )
        assert leveled.status_code == 200
        assert leveled.json()["outcome"]["new_level"] == 2

        rested = client.post(
            "/v3/campaigns/c1/actors/hero/rest",
            headers=OWNER,
            json={"command_id": "life:3", "kind": "short"},
        )
        assert rested.status_code == 200
        assert rested.json()["lifecycle"]["resources"]["focus"]["current"] == 1


def test_authoritative_rule_scene_studio_and_distribution_api() -> None:
    with TestClient(create_app()) as client:
        _create_campaign_and_actor(client)

        rule = {
            "rule_id": "demo.buff",
            "entry_point": "write",
            "allowed_state_paths": ["actor.bonus"],
            "nodes": {
                "write": {
                    "node_id": "write",
                    "op": "state",
                    "args": {"path": "actor.bonus", "value": 2},
                    "next_node": "emit",
                },
                "emit": {
                    "node_id": "emit",
                    "op": "emit",
                    "args": {"event": "demo.buff.applied"},
                },
            },
        }
        result = client.post(
            "/v3/campaigns/c1/rules/execute",
            headers=OWNER,
            json={
                "command_id": "rule:1",
                "document": rule,
                "state": {"actor": {"bonus": 0}},
                "entity_id": "hero",
                "component": "rule_state",
            },
        )
        assert result.status_code == 200
        assert result.json()["state"]["actor"]["bonus"] == 2
        events = client.get("/v3/campaigns/c1/events", headers=OWNER).json()
        assert events[-1]["kind"] == "rule.executed"

        scene = {
            "scene_id": "town",
            "scene_type": "settlement",
            "entity_ids": ["hero"],
            "preload_entity_ids": [],
            "next_scene_ids": [],
        }
        assert client.post("/v3/campaigns/c1/scenes", headers=OWNER, json=scene).status_code == 200
        assert client.post("/v3/campaigns/c1/scenes/town/loading", headers=OWNER).status_code == 200
        active = client.post("/v3/campaigns/c1/scenes/town/active", headers=OWNER)
        assert active.status_code == 200
        assert active.json()["status"] == "active"

        project = {
            "project_id": "studio-1",
            "name": "Starter Adventure",
            "document": {"map": {"nodes": [{"id": "town"}]}, "rules": [rule]},
        }
        assert client.post("/v3/studio/projects", json=project).status_code == 200
        snapshot = client.post("/v3/studio/projects/studio-1/snapshot")
        assert snapshot.status_code == 200
        assert len(snapshot.json()["revisions"]) == 1
        publish = client.post(
            "/v3/studio/projects/studio-1/publish",
            json={"package_id": "starter.adventure", "version": "1.0.0"},
        )
        assert publish.status_code == 200
        lock = client.get("/v3/distribution/resolve/starter.adventure")
        assert lock.status_code == 200
        assert lock.json()["releases"][0][0] == "starter.adventure"
