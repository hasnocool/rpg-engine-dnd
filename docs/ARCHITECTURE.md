# Architecture

## Design principles

1. **Headless authority** — clients submit commands; clients do not mutate game truth.
2. **Deterministic simulation** — a seed, snapshot, and ordered command stream define a run.
3. **Component composition** — entities remain lightweight and features attach as data.
4. **Ruleset separation** — generic simulation does not hard-code SRD mechanics.
5. **Async persistence** — database calls use an asynchronous boundary.
6. **Evolution without rewrites** — v0.1 boundaries are shaped for later runtime, event-sourcing, multiplayer, and distributed-world milestones.

## v0.1 modules

- `models.py`: entities, components, world state, ability-score value object.
- `commands.py`: immutable authoritative inputs.
- `events.py`: immutable authoritative outputs.
- `dice.py`: deterministic named PRNG streams and dice expressions.
- `stats.py`: pure stat/check helpers.
- `engine.py`: validation and state mutation authority.
- `persistence.py`: async SQLite snapshots.

## Forward compatibility

The roadmap's v1.2 `RulesRuntime` can become a delegated decision layer beneath `SimulationEngine`; v1.3 can persist emitted events and canonical state hashes; v1.7 can swap the persistence contract to PostgreSQL; v2.3 can project world state into knowledge-scoped views; and v3.0 can place authoritative worlds behind shard ownership.

No frontend or narrator should bypass the command boundary.
