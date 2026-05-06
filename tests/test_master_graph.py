"""Tests für Master-Graph: parallele Slave-Execution, assemble, Routing."""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from src.agent.slaves.assemble import assemble_node, _expand_notes
from src.agent.master_graph import plan_node, fan_out_to_slaves, route_after_assemble


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _base_state(**overrides):
    state = {
        "messages": [HumanMessage(content=(
            "Erstelle einen Rock-Guitar-Riff: Phase-4, Distortion, Amp, "
            "E-Moll-Pentatonik, 120 BPM, 40 Beats"
        ))],
        "track_count": 0,
        "tracks": [],
        "tempo": 120.0,
        "bridge_ok": False,
        "generation_phase": "idle",
        "song_blueprint": None,
        "section_timeline": [],
        "quality_report": None,
        "pending_sections": [],
        "retry_count": 0,
        "slave_plan": None,
        "slave_results": [],
        "assembled_json": None,
        "build_result": None,
        "slave_retry_counts": {},
    }
    state.update(overrides)
    return state


# ── plan_node ─────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_plan_node_extracts_bpm_and_beats():
    state = _base_state()
    result = plan_node(state)
    plan = result["slave_plan"]
    assert plan["bpm"] == 120.0
    assert plan["beat_count"] == 40.0


@pytest.mark.unit
def test_plan_node_extracts_instrument_hint():
    state = _base_state()
    result = plan_node(state)
    plan = result["slave_plan"]
    assert plan["instrument_hint"] == "Phase-4"


@pytest.mark.unit
def test_plan_node_extracts_fx_hint():
    state = _base_state()
    result = plan_node(state)
    plan = result["slave_plan"]
    assert "distortion" in plan["fx_hint"].lower()


@pytest.mark.unit
def test_plan_node_resets_slave_state():
    """plan_node muss slave_results und assembled_json zurücksetzen."""
    state = _base_state(
        slave_results=[{"type": "instrument", "instrument": "old"}],
        assembled_json='{"old": true}',
    )
    result = plan_node(state)
    assert result["slave_results"] == []
    assert result["assembled_json"] is None


# ── fan_out_to_slaves ─────────────────────────────────────────────────────────

@pytest.mark.unit
def test_fan_out_sends_both_slaves():
    from langgraph.types import Send
    state = _base_state(slave_plan={"bpm": 120, "beat_count": 40})
    sends = fan_out_to_slaves(state)
    node_names = [s.node for s in sends]
    assert "instrument_slave" in node_names
    assert "harmony_slave" in node_names
    assert len(sends) == 2


# ── assemble_node ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_assemble_merges_instrument_and_notes():
    import json
    state = _base_state(
        slave_plan={"bpm": 120, "beat_count": 8, "user_text": "test"},
        slave_results=[
            {"type": "instrument", "instrument": "Phase-4", "fx": ["Distortion", "Amp"]},
            {"type": "harmony", "key": "E minor", "allowed_pitch_classes": [4, 7, 9, 11, 2]},
            {"type": "notes", "bpm": 120.0, "length_beats": 8.0, "notes": [
                {"step": 0.0, "pitch": 52, "vel": 0.8, "dur": 0.5},
                {"step": 0.5, "pitch": 50, "vel": 0.7, "dur": 0.5},
            ]},
        ],
    )
    result = assemble_node(state)
    assert result["assembled_json"] is not None
    proj = json.loads(result["assembled_json"])
    assert proj["bpm"] == 120.0
    track = proj["tracks"][0]
    assert track["instrument"] == "Phase-4"
    assert "Distortion" in track["fx"]
    assert len(track["clip"]["notes"]) >= 2


@pytest.mark.unit
def test_assemble_returns_none_if_slave_missing():
    state = _base_state(
        slave_plan={"bpm": 120, "beat_count": 8},
        slave_results=[
            {"type": "instrument", "instrument": "Phase-4", "fx": []},
            {"type": "harmony", "key": "E minor", "allowed_pitch_classes": [4, 7, 9, 11, 2]},
            # note_slave fehlt
        ],
    )
    result = assemble_node(state)
    assert result["assembled_json"] is None


@pytest.mark.unit
def test_assemble_errors_on_max_retries():
    state = _base_state(
        slave_plan={"bpm": 120, "beat_count": 8},
        slave_results=[
            {"type": "instrument", "error": "parse_failed", "retry": True},
            {"type": "notes", "error": "parse_failed", "retry": True},
        ],
        slave_retry_counts={"instrument": 3, "notes": 3},
    )
    result = assemble_node(state)
    assert result["generation_phase"] == "error"


# ── _expand_notes ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_expand_notes_fills_target_beats():
    notes = [
        {"step": 0.0, "pitch": 52, "vel": 0.8, "dur": 0.5},
        {"step": 0.5, "pitch": 50, "vel": 0.7, "dur": 0.5},
    ]
    expanded = _expand_notes(notes, target_beats=4.0, pattern_beats=1.0)
    # 2 Noten pro Beat × 4 Beats = 8 Noten
    assert len(expanded) == 8
    assert expanded[2]["step"] == 1.0  # zweite Wiederholung


@pytest.mark.unit
def test_expand_notes_no_expansion_when_target_equals_pattern():
    notes = [{"step": 0.0, "pitch": 60, "vel": 0.8, "dur": 1.0}]
    result = _expand_notes(notes, target_beats=8.0, pattern_beats=8.0)
    assert len(result) == 1


# ── route_after_assemble ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_route_execute_build_when_json_present():
    state = _base_state(assembled_json='{"bpm": 120, "tracks": []}')
    assert route_after_assemble(state) == "execute_build"


@pytest.mark.unit
def test_route_reply_when_no_json():
    state = _base_state(assembled_json=None)
    assert route_after_assemble(state) == "reply"
