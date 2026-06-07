"""Unit-Tests für Step-Modelle + BitwigResultBuilder — set_send (C.1) und
setup_drum_machine (C.3).

Verifiziert die typisierte Konstruktion und die dict-Serialisierung
(model_dump → {type, args, status, note}) die der Executor/die OSC-Bridge
an die Java-Extension schickt. Kein Neo4j, kein Bitwig nötig.
"""
import pytest
from pydantic import ValidationError

from src.agent.models import (
    BitwigResultBuilder,
    SetSendStep,
    SetupDrumMachineStep,
)
from src.agent.models.steps import AddTrackStep

pytestmark = pytest.mark.unit


# ── C.2: add_track group ──────────────────────────────────────────────────────

def test_add_track_group_dump_shape():
    step = AddTrackStep(track_type="group")
    d = step.model_dump()
    assert d["type"] == "add_track"
    assert d["args"] == {"track_type": "group"}


def test_add_track_rejects_unknown_type():
    with pytest.raises(ValidationError):
        AddTrackStep(track_type="bus")


def test_builder_add_track_group_roundtrip():
    result = (BitwigResultBuilder(context_type="song")
              .add_track("group")
              .add_track("instrument")
              .build())
    types = [s.track_type for s in result.steps if isinstance(s, AddTrackStep)]
    assert types == ["group", "instrument"]


# ── C.1: set_send ─────────────────────────────────────────────────────────────

def test_set_send_step_dump_shape():
    step = SetSendStep(track_index=3, send_index=0, level=0.5)
    d = step.model_dump()
    assert d["type"] == "set_send"
    assert d["args"] == {"track_index": 3, "send_index": 0, "level": 0.5}


def test_set_send_level_is_clamped_by_validation():
    # level außerhalb [0,1] → ValidationError (Bereichsschutz im Modell)
    with pytest.raises(ValidationError):
        SetSendStep(track_index=1, send_index=0, level=1.5)
    with pytest.raises(ValidationError):
        SetSendStep(track_index=1, send_index=0, level=-0.1)


def test_builder_set_send_roundtrip():
    result = (BitwigResultBuilder(context_type="track")
              .add_track("return")
              .set_send(track_index=2, send_index=1, level=0.3)
              .build())
    steps = result.steps if hasattr(result, "steps") else result["steps"]
    send_steps = [s for s in _as_dicts(steps) if s["type"] == "set_send"]
    assert len(send_steps) == 1
    assert send_steps[0]["args"] == {"track_index": 2, "send_index": 1, "level": 0.3}


# ── C.3: setup_drum_machine ───────────────────────────────────────────────────

def test_setup_drum_machine_dump_shape():
    pads = [{"pad": 0, "name": "E-Kick"}, {"pad": 1, "name": "E-Snare"}]
    step = SetupDrumMachineStep(track_index=1, pads=pads)
    d = step.model_dump()
    assert d["type"] == "setup_drum_machine"
    assert d["args"]["track_index"] == 1
    assert d["args"]["pads"] == pads


def test_setup_drum_machine_defaults_empty_pads():
    step = SetupDrumMachineStep(track_index=4)
    assert step.pads == []
    assert step.model_dump()["args"]["pads"] == []


def test_builder_setup_drum_machine_roundtrip():
    pads = [{"pad": 0, "name": "E-Kick", "uuid": "abc"}]
    result = (BitwigResultBuilder(context_type="track")
              .add_track("instrument")
              .setup_drum_machine(track_index=1, pads=pads)
              .build())
    steps = result.steps if hasattr(result, "steps") else result["steps"]
    dm = [s for s in _as_dicts(steps) if s["type"] == "setup_drum_machine"]
    assert len(dm) == 1
    assert dm[0]["args"]["pads"] == pads


def _as_dicts(steps):
    out = []
    for s in steps:
        out.append(s.model_dump() if hasattr(s, "model_dump") else s)
    return out
