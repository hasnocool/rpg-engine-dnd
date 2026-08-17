"""Packaged CLI entrypoints for local play, TUI, API hosting, and worker heartbeats."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Sequence

from .commands import CreateEntity
from .engine import SimulationEngine
from .hosting import WorkerRecord, WorkerRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpg-engine")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="command")

    demo = sub.add_parser("demo", help="run a deterministic local simulation demo")
    demo.add_argument("--seed", default="demo")

    serve = sub.add_parser("serve", help="run the REST/WebSocket/Studio platform")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("tui", help="launch the Textual client")

    worker = sub.add_parser("worker", help="run a simulation-worker heartbeat loop")
    worker.add_argument("--worker-id", required=True)
    worker.add_argument("--capacity", type=int, default=8)
    worker.add_argument("--heartbeat-seconds", type=float, default=10.0)

    return parser


async def _demo(seed: str) -> int:
    engine = SimulationEngine(seed=seed)
    event = engine.handle(
        CreateEntity(
            command_id="demo:1",
            entity_id="hero",
            components={"identity": {"name": "Hero"}},
        )
    )
    print(json.dumps(event.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


async def _worker(worker_id: str, capacity: int, heartbeat_seconds: float) -> int:
    if heartbeat_seconds <= 0:
        raise ValueError("heartbeat interval must be positive")
    registry = WorkerRegistry()
    record = WorkerRecord(worker_id=worker_id, capacity=capacity)
    while True:
        await registry.heartbeat(record)
        print(json.dumps({"worker_id": worker_id, "status": "healthy", "capacity": capacity}))
        await asyncio.sleep(heartbeat_seconds)


def main(argv: Sequence[str] | None = None) -> int:
    from . import __version__

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command == "demo":
        return asyncio.run(_demo(args.seed))
    if args.command == "serve":
        import uvicorn

        uvicorn.run("rpg_engine_dnd.api:app", host=args.host, port=args.port, reload=False)
        return 0
    if args.command == "tui":
        from .tui import run_tui

        run_tui()
        return 0
    if args.command == "worker":
        try:
            return asyncio.run(_worker(args.worker_id, args.capacity, args.heartbeat_seconds))
        except KeyboardInterrupt:
            return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
