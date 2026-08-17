import pytest

from rpg_engine_dnd import CreateEntity, PatchComponent, SetComponent, SimulationEngine


def test_commands_mutate_authoritative_state_and_emit_sequence() -> None:
    engine = SimulationEngine(seed=7)
    created = engine.handle(CreateEntity(command_id="1", entity_id="hero", components={"hp": {"current": 10, "maximum": 10}}))
    patched = engine.handle(PatchComponent(command_id="2", entity_id="hero", component="hp", patch={"current": 7}))
    set_event = engine.handle(SetComponent(command_id="3", entity_id="hero", component="position", value={"x": 1, "y": 2}))
    assert (created.sequence, patched.sequence, set_event.sequence) == (1, 2, 3)
    assert engine.world.entities["hero"].components["hp"]["current"] == 7


def test_failed_command_does_not_advance_revision() -> None:
    engine = SimulationEngine(seed=7)
    engine.handle(CreateEntity(command_id="1", entity_id="hero"))
    with pytest.raises(ValueError):
        engine.handle(CreateEntity(command_id="2", entity_id="hero"))
    assert engine.world.revision == 1
