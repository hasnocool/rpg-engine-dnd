# Architecture

## Core invariants

1. **One authority boundary.** `WorldPlatformEngine` and its delegated runtimes mutate game truth; adapters do not.
2. **Deterministic inputs.** A root seed, initial state and ordered command stream define deterministic outcomes.
3. **Serializable composition.** Entity state is component data rather than frontend-specific objects.
4. **Ruleset separation.** Generic simulation stays independent from SRD-specific interpretation.
5. **Knowledge is not truth.** Player/spectator projections are constructed from perception/knowledge, never direct hidden-state references.
6. **Async I/O.** SQLite/PostgreSQL/network operations remain async; blocking file/CPU work is offloaded from event-loop threads.
7. **Hashable state.** Canonical JSON and SHA-256 underpin journals, visual deltas, content locks and shard transfers.
8. **Proposal-only intelligence.** AI directors/actors produce explanations and command-shaped proposals; they do not mutate authoritative state directly.

## Layer map

```text
Presentation and transport
  cli.py, tui.py, browser.py, frontends.py, api.py, visual.py
                            |
                            v
Authority and orchestration
  world_platform.py, engine.py, orchestrator.py, multiplayer.py
             |                         |
             v                         v
Rules / lifecycle / AI           knowledge.py
  rules.py, compiler.py          visual_runtime.py
  lifecycle.py, actors.py             |
  combat.py, adventure.py             |
  living_world.py                     |
             +------------+-----------+
                          v
Deterministic state/history
  models.py, events.py, dice.py, canonical.py, event_sourcing.py
                          |
                          v
Async persistence / hosting
  persistence.py, hosting.py, studio.py, distribution.py
                          |
                          v
Distributed authority
  sharding.py
```

## Authoritative command flow

A client submits a typed command. The campaign runtime verifies client authority, then dispatches through `WorldPlatformEngine`. The engine validates/mutates state and emits an immutable event. Campaign services append/publish that event. Client-facing reads and event history are filtered by `KnowledgeAuthority` unless the caller has campaign-owner authority.

Executable content follows the same boundary. `RuleExecuteCommand` is compiled by `RuleCompiler`, validated against bounded operations/state paths, executed by `RuleInterpreter` through `RulesRuntime`, written into authoritative state when requested, and represented by a `rule.executed` event.

## Deterministic rules and event history

`RulesRuntime` owns named deterministic roll streams, modifier traces, attack/damage outcomes, deterministic effects, trigger hooks, reaction opportunities and action economy. `CombatSystem` may delegate attack/damage resolution into it instead of maintaining a second source of truth.

`EventJournal` stores deterministic patches plus canonical before/after hashes and a hash of each entry including the previous entry hash. This enables:

- verification;
- replay and rewind;
- campaign branching;
- command-ID idempotency;
- eventual persistence using the same JSON storage contract.

## Spatial authority

Spatial rules are transport-neutral:

- `GraphSpace`: capacities and weighted routing;
- `GridSpace`: occupancy, terrain cost, pathfinding, line-of-sight and cover;
- `ContinuousSpace`: bounded 2D/3D movement and collision.

Clients can visualize these spaces but cannot override occupancy/collision/movement decisions.

## Knowledge authority

`KnowledgeAuthority` stores per-actor `KnownEntity` snapshots and facts. Observations of another entity retain only configured public components. An actor's own live state can be visible to itself; remembered remote entities do not become live hidden-state references.

The v3 REST/event/WebSocket profile therefore exposes:

- spectator: public shell;
- player: knowledge view for an owned actor;
- campaign owner: explicitly omniscient view.

## Persistence and process ownership

`AsyncPersistence` defines `initialize`, `put_json`, `get_json`, and `list_json`. Implementations include async SQLite platform storage and async PostgreSQL storage. The same contract supports journal entries, Studio projects/revisions, package releases/locks, shard metadata, assignments, transfers, and cross-shard messages.

Production hosting primitives add worker heartbeats, stable capacity-aware rendezvous placement, PostgreSQL campaign leases, and hashed reconnect/resume tickets with event-sequence checkpoints.

## Distributed world authority

v3.0 does not pretend a single process is a distributed system. Instead it provides deterministic primitives that external transport/service-discovery infrastructure can wrap:

1. shard heartbeats and status/capacity;
2. region-affine rendezvous routing and deterministic rebalance plans;
3. Lamport-ordered, idempotent cross-shard messages;
4. two-phase entity handoff: prepare, accept, commit/abort;
5. canonical transfer payload hashes;
6. exactly-once committed-transfer guard per target shard/entity;
7. shared persistence metadata compatible with the v1.7 hosting layer.

These contracts allow multiple simulation processes to be introduced without changing campaign, rules, content, or client schemas.
