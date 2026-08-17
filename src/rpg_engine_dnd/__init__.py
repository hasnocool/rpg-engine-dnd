"""Public API for rpg-engine-dnd v3.3."""

from .commands import (
    Command,
    CreateEntity,
    DeleteEntity,
    PatchComponent,
    RemoveComponent,
    SetComponent,
)
from .dice import DiceRoll, DiceStreams
from .engine import SimulationEngine
from .events import Event
from .mechanics import Modifier, ModifierOperation, ModifierResolver, ReactionStack, ReactionWindow
from .models import AbilityScores, Entity, World
from .persistence import AsyncSQLitePlatformStore, AsyncSQLiteStore
from .rules import RulesRuntime, SRDRulesRuntime
from .runtime import AuthoritativeRuntime, CommandBus, ComponentSchemaRegistry, WorldTransaction
from .scheduler import ScheduleDomain, SimulationScheduler
from .semantic_events import DomainEvent, SemanticEventJournal
from .spatial_query import HexGridSpace, SpatialQueryService
from .stats import CheckOutcome, ability_modifier, resolve_check

__all__ = [
    "AbilityScores",
    "AsyncSQLitePlatformStore",
    "AsyncSQLiteStore",
    "AuthoritativeRuntime",
    "CheckOutcome",
    "Command",
    "CommandBus",
    "ComponentSchemaRegistry",
    "CreateEntity",
    "DeleteEntity",
    "DiceRoll",
    "DiceStreams",
    "DomainEvent",
    "Entity",
    "Event",
    "HexGridSpace",
    "Modifier",
    "ModifierOperation",
    "ModifierResolver",
    "PatchComponent",
    "ReactionStack",
    "ReactionWindow",
    "RemoveComponent",
    "RulesRuntime",
    "SRDRulesRuntime",
    "ScheduleDomain",
    "SemanticEventJournal",
    "SetComponent",
    "SimulationEngine",
    "SimulationScheduler",
    "SpatialQueryService",
    "World",
    "WorldTransaction",
    "ability_modifier",
    "resolve_check",
]

__version__ = "3.3.0"
