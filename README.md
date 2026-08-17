# rpg-engine-dnd

`rpg-engine-dnd` is a **headless, deterministic tabletop-RPG simulation engine**.
Presentation is deliberately separate from game truth: the same campaign state can later
be driven by a CLI, TUI, browser, REST/WebSocket client, Godot adapter, multiplayer host,
or AI narrator without changing authoritative rules state.

## Current milestone: v0.1 Core Simulation

Implemented:

- entity/component world state;
- typed commands and events;
- deterministic named dice streams;
- ability modifiers and deterministic checks;
- authoritative command dispatch;
- async SQLite persistence;
- canonical JSON snapshots suitable for replay-oriented evolution;
- Python 3.12 test and CI baseline.

The complete long-term roadmap from the project specification is tracked in
[`docs/ROADMAP.md`](docs/ROADMAP.md). It reaches tactical combat, adventure simulation,
living worlds, multiple clients, visual adapters, AI GM support, multiplayer, creator
tools, an SRD 5.2.1 rules layer, deterministic event sourcing, distributed hosting, and
massively persistent worlds.

## Architecture

```text
clients/adapters (future)
        |
        v
     Command
        |
        v
+-------------------+
| SimulationEngine  |  authoritative validation/dispatch
+---------+---------+
          |
          +------> deterministic RNG streams
          |
          v
       World
  entities/components
          |
          +------> Events
          |
          v
 Async SQLite snapshots
```

The v0.1 core is intentionally ruleset-neutral. D&D/SRD-specific mechanics belong behind
the ruleset boundary described by the v1.1+ roadmap rather than leaking into generic
simulation primitives.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
```

```python
from rpg_engine_dnd import AbilityScores, CreateEntity, SimulationEngine

engine = SimulationEngine(seed=42)
event = engine.handle(
    CreateEntity(
        command_id="create-hero",
        entity_id="hero",
        components={"abilities": AbilityScores(strength=16).model_dump()},
    )
)
print(event)
```

## Determinism contract

Given the same initial snapshot, root seed, and ordered command stream, the engine must
produce the same authoritative state and dice results. Randomness is partitioned into
stable **named streams** so adding an unrelated roll in one subsystem does not perturb a
different subsystem's sequence.

## Persistence contract

SQLite I/O uses `aiosqlite`; public persistence methods are async and do not block the
event loop with synchronous database calls. Snapshots are canonical JSON, making them
stable inputs for the roadmap's later state hashing, journals, replay, rewind, and
branching.

## License

MIT. SRD content is not bundled in v0.1. Any future SRD package must preserve its own
provenance and licensing metadata.
