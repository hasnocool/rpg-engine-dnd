"""Textual TUI client for the local deterministic engine."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static


class RPGEngineTUI(App[None]):
    TITLE = "rpg-engine-dnd"
    SUB_TITLE = "Deterministic RPG Platform"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Static("rpg-engine-dnd v3.0\nUse the REST/WebSocket API or CLI demo to drive authoritative state.", id="status")
        yield Footer()


def run_tui() -> None:
    RPGEngineTUI().run()
