# Roadmap implementation matrix

This file maps roadmap milestones to concrete implementation surfaces. The roadmap itself remains in [`ROADMAP.md`](ROADMAP.md).

| Milestone | Primary implementation | Key result |
| --- | --- | --- |
| v0.1 Core Simulation | `models.py`, `commands.py`, `events.py`, `dice.py`, `stats.py`, `engine.py`, `persistence.py` | Deterministic ECS-like world, commands/events and async snapshots |
| v0.2 Tactical RPG | `combat.py` | Initiative, actions, movement/path/LOS, effects, items and delayed resolution |
| v0.3 Adventure Engine | `adventure.py` | Graph maps, discoveries, dialogue, quests, NPC profiles and shops |
| v0.4 Living World | `living_world.py` | World clocks, weather, factions, schedules, economy and dynamic events |
| v0.5 Multiple Frontends | `cli.py`, `tui.py`, `frontends.py`, `api.py`, `browser.py` | CLI/TUI/live text/REST/WebSocket/browser adapters |
| v0.6 Visual Game Adapters | `visual.py` | Godot 2D/3D bridge and scene/asset bindings |
| v0.7 AI Game Master | `ai.py` | Event narrator boundary, personalities, procedural encounters/quests, bounded memory |
| v0.8 Multiplayer | `multiplayer.py` | Sessions, parties, spectators, ownership and hosting |
| v0.9 Creator Platform | `creator.py` | Typed editor data, validation and deterministic mod ZIP format |
| v1.0 RPG Platform | `platform.py`, `api.py` | Hosted/marketplace models and versioned public API |
| v1.1 SRD 5.2.1 Foundation | `srd.py` | Opt-in provenance boundary and structured mechanical helpers |
| v1.2 Rules Runtime + Effect Pipeline | `rules.py`, `combat.py` | Typed runtime, modifier traces, effects/hooks/reactions/action economy |
| v1.3 Deterministic Event Sourcing | `canonical.py`, `event_sourcing.py` | Patches, canonical hashes, chained journals, replay/rewind/branching/idempotency |
| v1.4 Spatial Authority | `spatial.py` | Graph/grid/continuous authority, collision, pathfinding, LOS, cover and terrain |
| v1.5 Intelligent Living Actors | `actors.py` | Perception, goals, utility, behaviors, schedules, memory and command proposals |
| v1.6 Character Lifecycle | `lifecycle.py`, `api.py` | Builds, multiclass progression, resources/rests/equipment and authoritative endpoints |
| v1.7 Production Campaign Hosting | `hosting.py`, `persistence.py`, `cli.py` | PostgreSQL, migrations, workers, leases, placement and reconnect tickets |
| v1.8 Creator Studio | `studio.py`, `browser.py`, `api.py` | Persistent projects/revisions, SVG map editor, structured editors, publish flow |
| v1.9 Executable Content Compiler + Rules Graph | `compiler.py`, `world_platform.py`, `api.py` | Bounded declarative graph compiler/interpreter and authoritative `rule.execute` |
| v2.0 Campaign Orchestrator | `orchestrator.py`, `api.py` | Typed scene lifecycle, transitions, preload/stream projections |
| v2.1 Simulation Lab | `lab.py` | Seed matrices, bounded concurrency and deterministic aggregate reports |
| v2.2 Advanced AI Director | `director.py` | Explainable ranked proposal-only campaign direction |
| v2.3 Perception + Knowledge Authority | `knowledge.py`, `api.py` | Remembered observations, redacted views and v3 scoped reads/events |
| v2.4 Visual Runtime SDK | `visual_runtime.py` | Deterministic snapshots, visual bindings and hash-verified deltas |
| v2.5 Content Distribution Platform | `distribution.py`, `api.py` | SemVer dependencies, compatibility, locks, signing interface and upgrade plans |
| v3.0 Massively Persistent Worlds | `sharding.py`, `hosting.py` | Shards, regional routing, Lamport messages, 2-phase handoff and persistent metadata |

## Validation strategy

The test suite is split into core tests plus cross-milestone regression suites:

- `test_v02_v10_platform.py` covers tactical/adventure/world/client/creator foundations;
- `test_v11_v19_runtime.py` covers SRD/rules/event/spatial/AI/lifecycle/compiler foundations;
- `test_v20_v30_platform.py` covers orchestration/lab/director/knowledge/visual/distribution/sharding;
- `test_api_v3.py` proves public authority/redaction/lifecycle/rules/Studio/distribution integration;
- `test_persistence_adapters.py` proves multiple milestones share one async persistence contract.

CI targets Python 3.12 and runs Ruff, mypy and pytest.
