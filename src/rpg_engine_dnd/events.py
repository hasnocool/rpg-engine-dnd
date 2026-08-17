"""Authoritative events emitted after successful command application."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sequence: int = Field(ge=1)
    command_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    entity_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
