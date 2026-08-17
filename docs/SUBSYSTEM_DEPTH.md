# v3.0.1–v3.3.0 subsystem depth

This upgrade series deepens the existing v0.1–v3.0 systems instead of adding a disconnected feature layer.

## v3.0.1 — deterministic invariant coverage

- dedicated subsystem-depth regression suite;
- atomic-authority/journal checks;
- scheduler ordering/cancellation checks;
- shard fencing/idempotency checks;
- GOAP, reactions, content trust, knowledge, spatial, lifecycle, compiler and balancing checks.

## v3.0.2 — unified authoritative runtime

- extensible `CommandBus`;
- validation and authorization pipelines;
- `AuthoritativeRuntime` rollback boundary;
- `WorldTransaction`, `MutationSet`, and `EventBatch` primitives;
- typed component schema registry and sequential migrations;
- `WorldPlatformEngine` core/rule commands wired through the command bus.

## v3.0.3 — tactical/spatial consolidation

- `SpatialQueryService` as the common path/distance/visibility/cover/occupancy façade;
- deterministic axial `HexGridSpace` alongside existing graph/grid/continuous authority;
- rules runtime remains the combat attack/damage authority while generalized modifiers now feed attack/damage resolution.

## v3.0.4 — universal scheduler

`SimulationScheduler` provides one deterministic timeline for turn readiness, spells, conditions, AI, NPC schedules, quests, weather, travel, downtime, crafting, resting, respawns, world events and shard timers. Async wrappers use an `asyncio.Lock` and perform no blocking I/O.

## v3.0.5 — semantic events and snapshots

- human-readable `DomainEvent` paired with deterministic structural journal entries;
- canonical snapshot hashes;
- journal segmentation and segment hashes;
- async snapshot/domain-event persistence bridge.

## v3.0.6 — generalized mechanics

- modifier algebra: add/multiply/set/min/max/advantage/disadvantage/cancel/replace;
- deterministic stacking groups and priorities;
- reaction windows, eligible actors, priority ordering and stack resolution;
- `RulesRuntime` integration for scoped attack/damage modifiers.

## v3.0.7 — living-world depth

- event-driven quest objective graphs;
- settlement production/consumption and scarcity pricing;
- trade-route model;
- faction relationship graph, territory/resources/goals/strength/influence state;
- regional climate, seasonal temperature, fronts, visibility/wind/precipitation/travel effects.

## v3.0.8 — actor intelligence

- multi-consideration utility scoring with response curves;
- bounded deterministic GOAP planning;
- episodic, semantic, relationship, location and threat memories;
- confidence decay and memory consolidation.

## v3.0.9 — Creator Studio tooling

- rule trace debugger model;
- breakpoints and step/continue semantics;
- state diffs and watch-path model;
- content reference/dependency graph;
- simulation-preview result model.

## v3.1.0 — distributed authority hardening

- shard epochs, lease IDs and monotonic fencing tokens;
- atomic compare-and-set JSON persistence in SQLite and PostgreSQL;
- CAS retry loop for process-safe shard lease acquisition;
- durable idempotency claims, message storage and dead-letter records;
- transfer leases and retry policy primitives;
- hosting backpressure, circuit breakers, worker generations and checkpoints.

## v3.2.0 — large-world client streaming

- shared command/event/snapshot/delta protocol;
- expected-world-revision optimistic concurrency;
- capability and asset-binding manifests;
- area-of-interest filtering;
- priority tiers and LOD metadata.

## v3.3.0 — predictive simulation and director support

- Monte Carlo balance samples/reports;
- bounded async scenario execution with semaphore backpressure;
- outcome, rounds, HP, resource-spend and action-efficiency statistics;
- regression thresholds;
- predictive director candidate ranking.

## Cross-cutting upgrades

- generalized feature grants/prerequisites/resources/progression tables for lifecycle/homebrew;
- typed rule IR with reference validation, dead-node elimination, capability analysis and gas estimation;
- hierarchical scene trees with independently active/suspended background simulation;
- provenance-rich knowledge facts for rumors, deception, shared knowledge and intelligence;
- Ed25519 publisher verification, publisher identity, package capabilities, trust policy and SBOM metadata.

The design remains backward-compatible: existing v0.1–v3.0 modules and APIs continue to exist, while the new depth layers provide the preferred integration points for future engine work.
