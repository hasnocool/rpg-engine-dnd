# rpg-engine-dnd

`rpg-engine-dnd` is a **headless, deterministic tabletop-RPG simulation and persistent-world platform** for Python 3.12+.

The authoritative game model is deliberately independent from presentation. The same campaign can be driven through the packaged CLI, a live text stream, Textual TUI, REST/WebSocket API, browser client, Godot 2D/3D bridge, multiplayer host, creator tooling, or AI director without allowing any of those adapters to bypass game-state authority.

**Current implementation: v3.0.0 — Massively Persistent Worlds foundation.** The implementation follows the project roadmap from v0.1 core simulation through v3.0 sharding, deterministic cross-shard messaging, and two-phase entity handoff.

## What is implemented

### Simulation and adventure — v0.1–v0.4

- entity/component world state, immutable commands, authoritative events;
- deterministic named RNG/dice streams and checks;
- async SQLite snapshots;
- tactical combat, deterministic initiative, movement/path/LOS, conditions, inventories, delayed actions;
- graph-map exploration, dialogue requirements, event-driven quests, NPC profiles, shops;
- world clocks, weather, factions/reputation, NPC schedules, economy, and dynamic events.

### Clients, AI, multiplayer, creators — v0.5–v1.0

- CLI, live-text adapter, Textual TUI, REST API, WebSocket event stream, built-in browser client;
- Godot 2D/3D scene and asset bindings;
- authoritative-event narrator boundary, bounded AI memory, generated encounter/quest proposals;
- campaign sessions, parties, spectators, ownership, campaign hosting primitives;
- typed campaign/map/creature/spell/quest/rules creator documents and deterministic mod ZIP validation;
- hosted-campaign/marketplace models and versioned public API metadata.

### Rules and production runtime — v1.1–v1.9

- opt-in SRD 5.2.1 provenance/licensing boundary without bundling copied rulebook prose;
- typed `RulesRuntime`, modifier traces, attacks/damage/effects/hooks/reactions/action economy;
- deterministic event journals, state patches/hashes, replay, rewind, branching, idempotency;
- graph/grid/continuous 2D/3D spatial authority, collision, pathfinding, LOS, cover and terrain costs;
- perception/goals/utility AI/behavior primitives/schedules/memory producing validated command proposals;
- rules-neutral character lifecycle, multiclass progression, resources, rests, equipment and attunement;
- async PostgreSQL persistence, schema migrations, worker heartbeats, leases, rendezvous placement, reconnect tickets;
- Creator Studio projects/revisions/editors and executable bounded rule graphs with no `eval`, `exec`, Lua, Python, or arbitrary scripts.

### Campaign platform and persistent worlds — v2.0–v3.0

- authoritative scene orchestration and streamed entity sets;
- deterministic simulation-lab seed matrices and aggregate comparison reports;
- proposal-only campaign-scale AI director;
- per-actor knowledge authority and remembered/redacted views;
- hash-verified visual snapshots/deltas;
- semantic-versioned content distribution, dependency resolution, locks, signing interface and upgrades;
- shard registry, regional rendezvous routing, Lamport-ordered cross-shard messages;
- two-phase entity transfer (`prepare -> accept -> commit/abort`), canonical payload verification and exactly-once commit guard;
- a shared async persistence contract used by SQLite/PostgreSQL and the journal, Studio, distribution, and distributed-world metadata adapters.

See [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) for the milestone-to-module matrix and [`docs/ROADMAP.md`](docs/ROADMAP.md) for the full source roadmap.

## Architecture

```text
 CLI / TUI / Browser / Godot / REST / WebSocket / AI / Multiplayer
                              |
                      commands / scoped views
                              |
                  +-----------v------------+
                  |   WorldPlatformEngine  |
                  | authoritative boundary |
                  +----+-------------+-----+
                       |             |
              +--------v----+   +----v---------+
              | Simulation  |   | RulesRuntime |
              | entity ECS  |   | effect graph |
              +------+------+
                     |
        +------------+-------------+
        |                          |
  Event journals            Knowledge authority
  hashes / replay           player-safe projections
        |                          |
        +------------+-------------+
                     |
           async persistence contract
             SQLite / PostgreSQL
                     |
          hosting / shard authority
         routing / messages / handoff
```

The central rule is simple: **clients render state and submit commands; they do not mutate authoritative truth.**

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'
```

Run the complete test suite:

```bash
ruff check .
mypy src
pytest
```

## Run

Deterministic local demo:

```bash
rpg-engine demo --seed campaign-42
```

Full REST/WebSocket/Creator Studio-capable service:

```bash
rpg-engine serve --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/` for the built-in browser client/editor. FastAPI exposes its generated OpenAPI document at `/openapi.json`.

Textual client:

```bash
rpg-engine tui
```

Simulation-worker heartbeat process:

```bash
rpg-engine worker --worker-id worker-west-1 --capacity 16
```

## Minimal authoritative simulation

```python
# examples/minimal_simulation.py
from rpg_engine_dnd import CreateEntity, SimulationEngine

engine = SimulationEngine(seed="campaign-42")
event = engine.handle(
    CreateEntity(
        command_id="create-hero",
        entity_id="hero",
        components={"identity": {"name": "Hero"}},
    )
)

print(event.model_dump(mode="json"))
print(engine.snapshot())
```

## Determinism and replay contract

Given the same initial snapshot, root seed, and ordered authoritative command stream, deterministic subsystems produce the same state and random outcomes. RNG is split into stable named streams so unrelated random activity does not silently perturb another subsystem.

Event journals add canonical SHA-256 before/after state hashes, hash-chained entries, replay/rewind/branching, and command-ID idempotency. Visual deltas and cross-shard transfer payloads use the same canonical hashing foundation.

## Knowledge and multiplayer authority

The v3 API is **knowledge-scoped by default**. Spectators receive only public component shells; players can request views for actors they own; owner credentials can request omniscient campaign state. Perception stores remembered snapshots rather than giving clients a stale reference to hidden live state.

## Async I/O contract

Persistence and network-facing APIs are asynchronous. SQLite uses `aiosqlite`, PostgreSQL uses `asyncpg`, multiplayer/websocket queues use `asyncio`, and file/ZIP or CPU-bound simulation work is explicitly moved off the event loop where necessary. Blocking database calls are not introduced into async code paths.

## SRD boundary

The generic engine does not copy or embed proprietary D&D books. The optional SRD layer stores structured compatibility/provenance metadata and generic mechanical helpers. Content packs are expected to carry their own provenance/license metadata.

## License

MIT for this repository's original code. Third-party content remains subject to its own license.
