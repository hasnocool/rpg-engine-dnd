"""Canonical serialization and hashing helpers shared by deterministic subsystems."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible data with stable ordering and no insignificant spaces."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    """Return the SHA-256 hash of a canonical JSON representation."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
