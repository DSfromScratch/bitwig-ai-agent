import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.policy import enforce_policy_on_response, is_concrete_track_task


@pytest.mark.unit
def test_detects_concrete_track_task():
    text = "Erstelle einen 20-sekündigen Rock-Riff mit Phase-4, Distortion und Amp bei 120 BPM"
    assert is_concrete_track_task(text) is True


@pytest.mark.unit
def test_rewrites_legacy_chain_to_build_song():
    state = {
        "messages": [
            HumanMessage(content="Erstelle einen Rock-Riff Track in E-Moll mit Distortion und Amp, 20 Sekunden bei 120 BPM"),
        ]
    }
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "check_bitwig_connection", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "setup_instrument_track", "args": {"track_index": 1, "instrument_name": "Phase-4"}, "id": "c2", "type": "tool_call"},
            {"name": "setup_instrument_track", "args": {"track_index": 1, "instrument_name": "Distortion"}, "id": "c3", "type": "tool_call"},
            {"name": "setup_instrument_track", "args": {"track_index": 1, "instrument_name": "Amp"}, "id": "c4", "type": "tool_call"},
            {"name": "bitwig_set_tempo", "args": {"bpm": 120}, "id": "c5", "type": "tool_call"},
            {"name": "write_notes_to_clip", "args": {"track_index": 1, "notes_json": "[{\"step\": 0, \"pitch\": 40, \"vel\": 0.8, \"dur\": 1.0}]"}, "id": "c6", "type": "tool_call"},
        ],
    )

    rewritten, meta = enforce_policy_on_response(state, response)
    names = [tc["name"] for tc in rewritten.tool_calls]

    assert meta["action"] == "rewrite"
    assert names[0] == "check_bitwig_connection"
    assert "build_song" in names
    assert "setup_instrument_track" not in names
    assert "write_notes_to_clip" not in names

    build_call = next(tc for tc in rewritten.tool_calls if tc["name"] == "build_song")
    payload = json.loads(build_call["args"]["project_json"])

    assert payload["bpm"] == 120
    assert payload["tracks"][0]["instrument"] == "Phase-4"
    assert payload["tracks"][0]["fx"] == ["Distortion", "Amp"]


@pytest.mark.unit
def test_allows_when_build_song_already_used():
    state = {"messages": [HumanMessage(content="Rock riff mit Phase-4 und Distortion")]} 
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "check_bitwig_connection", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "build_song", "args": {"project_json": "{}"}, "id": "c2", "type": "tool_call"},
        ],
    )

    out, meta = enforce_policy_on_response(state, response)
    assert out.tool_calls[1]["name"] == "build_song"
    assert meta["action"] == "allow"


@pytest.mark.unit
def test_strict_fx_chain_removes_extra_fx_on_rewrite():
    state = {
        "messages": [
            HumanMessage(content="Erstelle ein Rock-Riff mit Distortion und Amp FX-Chain, exakt diese Kette"),
        ]
    }
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "setup_instrument_track", "args": {"track_index": 1, "instrument_name": "Phase-4"}, "id": "c1", "type": "tool_call"},
            {"name": "setup_instrument_track", "args": {"track_index": 1, "instrument_name": "Distortion"}, "id": "c2", "type": "tool_call"},
            {"name": "setup_instrument_track", "args": {"track_index": 1, "instrument_name": "Amp"}, "id": "c3", "type": "tool_call"},
            {"name": "setup_instrument_track", "args": {"track_index": 1, "instrument_name": "Compressor"}, "id": "c4", "type": "tool_call"},
        ],
    )

    rewritten, meta = enforce_policy_on_response(state, response)
    build_call = next(tc for tc in rewritten.tool_calls if tc["name"] == "build_song")
    payload = json.loads(build_call["args"]["project_json"])

    assert meta["action"] == "rewrite"
    assert meta["strict_fx_request"] is True
    assert "strict_fx_chain_enforced" in meta["violations"]
    assert payload["tracks"][0]["fx"] == ["Distortion", "Amp"]



@pytest.mark.unit
def test_prefers_explicit_beats_from_prompt():
    state = {
        "messages": [
            HumanMessage(content="Rock-Riff Track, 40 beats, 120 BPM, mit Distortion und Amp FX-Chain"),
        ]
    }
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "setup_instrument_track", "args": {"track_index": 1, "instrument_name": "Phase-4"}, "id": "c1", "type": "tool_call"},
            {"name": "write_notes_to_clip", "args": {"track_index": 1, "notes_json": "[]"}, "id": "c2", "type": "tool_call"},
        ],
    )

    rewritten, _ = enforce_policy_on_response(state, response)
    build_call = next(tc for tc in rewritten.tool_calls if tc["name"] == "build_song")
    payload = json.loads(build_call["args"]["project_json"])
    assert payload["tracks"][0]["clip"]["length_beats"] == 40.0
