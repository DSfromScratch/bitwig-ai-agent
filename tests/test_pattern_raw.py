"""Tests für scripts/_note_plan_parser.py und write_pattern_raw."""
from __future__ import annotations

import pytest

from scripts._note_plan_parser import (
    parse_note_plan, to_write_pattern_raw_call, _parse_spec,
)

pytestmark = pytest.mark.unit


def test_parse_spec_single_start_with_dur():
    assert _parse_spec("s0,dur1") == [(0.0, 1.0)]


def test_parse_spec_multiple_starts_default_dur():
    assert _parse_spec("s0,s4,s8,s12") == [(0.0, 0.5), (4.0, 0.5),
                                            (8.0, 0.5), (12.0, 0.5)]


def test_parse_spec_with_modifier_ignored():
    assert _parse_spec("s0,dur8,Slide") == [(0.0, 8.0)]


def test_parse_note_plan_header_extracts_key_and_bpm():
    plan = "Notenplan Test (D major, 117 BPM):\n  Bass: D3=62 [s0,dur1]"
    parsed = parse_note_plan(plan)
    assert parsed["key"] == "D major"
    assert parsed["bpm"] == 117


def test_parse_note_plan_extracts_tracks_with_instruments():
    plan = """Notenplan X (E minor, 120 BPM):
  Bass-Track (FM-4): D3=62 [s0,dur1], D3=62 [s2,dur1]
  Drums: Kick=36 [s0,s4]
"""
    parsed = parse_note_plan(plan)
    roles = [t["role"] for t in parsed["tracks"]]
    assert "Bass-Track" in roles
    assert "Drums" in roles
    bass = next(t for t in parsed["tracks"] if t["role"] == "Bass-Track")
    assert bass["instrument"] == "FM-4"
    assert len(bass["notes"]) == 2
    assert all(0 <= n["pitch"] <= 127 for n in bass["notes"])


def test_parse_note_plan_returns_canonical_note_schema():
    plan = "Notenplan X (C minor, 120 BPM):\n  Bass (FM-4): D3=62 [s0,dur1]"
    parsed = parse_note_plan(plan)
    n = parsed["tracks"][0]["notes"][0]
    assert set(n.keys()) == {"pitch", "start", "dur", "vel"}
    assert isinstance(n["pitch"], int) and isinstance(n["start"], float)
    assert n["dur"] > 0


def test_parse_note_plan_handles_empty_or_none():
    assert parse_note_plan("")["tracks"] == []
    assert parse_note_plan(None)["tracks"] == []


def test_to_write_pattern_raw_call_rounds_length_to_full_bar():
    track = {"role": "Bass", "instrument": "FM-4",
             "notes": [{"pitch": 60, "start": 0, "dur": 1, "vel": 0.8},
                       {"pitch": 62, "start": 6, "dur": 1, "vel": 0.8}]}
    call = to_write_pattern_raw_call(track, bpm=120, key="C minor")
    assert call["tool"] == "write_pattern_raw"
    assert call["args"]["length_beats"] == 8.0  # 6+1=7 → nächster bar = 8
    assert call["args"]["bpm"] == 120
    assert call["args"]["key"] == "C minor"
    assert call["args"]["instrument"] == "FM-4"


def test_to_write_pattern_raw_call_empty_returns_empty():
    assert to_write_pattern_raw_call({"role": "X", "notes": []}) == {}


# ── write_pattern_raw Tool ────────────────────────────────────────────────────

def test_write_pattern_raw_validates_pitch_range():
    from src.agent.tools.music.pattern_raw_tool import validate_notes, NoteValidationError
    with pytest.raises(NoteValidationError, match="außerhalb 0-127"):
        validate_notes([{"pitch": 200, "start": 0, "dur": 1}], 4)


def test_write_pattern_raw_validates_negative_start():
    from src.agent.tools.music.pattern_raw_tool import validate_notes, NoteValidationError
    with pytest.raises(NoteValidationError, match="negativ"):
        validate_notes([{"pitch": 60, "start": -1, "dur": 1}], 4)


def test_write_pattern_raw_validates_empty_notes():
    from src.agent.tools.music.pattern_raw_tool import validate_notes, NoteValidationError
    with pytest.raises(NoteValidationError, match="leer"):
        validate_notes([], 4)


def test_write_pattern_raw_auto_converts_midi_velocity():
    from src.agent.tools.music.pattern_raw_tool import validate_notes
    # vel=100 (MIDI-int) → 100/127 ≈ 0.787
    out = validate_notes([{"pitch": 60, "start": 0, "dur": 1, "vel": 100}], 4)
    assert 0.7 < out[0]["vel"] < 0.8


def test_write_pattern_raw_accepts_aliases():
    from src.agent.tools.music.pattern_raw_tool import validate_notes
    out = validate_notes([{"pitch": 60, "step": 0, "length": 1, "velocity": 0.5}], 4)
    assert out[0]["step"] == 0 and out[0]["dur"] == 1 and out[0]["vel"] == 0.5


def test_write_pattern_raw_rejects_all_notes_outside_length():
    from src.agent.tools.music.pattern_raw_tool import validate_notes, NoteValidationError
    with pytest.raises(NoteValidationError, match="jenseits"):
        validate_notes([{"pitch": 60, "start": 10, "dur": 1}], length_beats=4)


def test_write_pattern_raw_sorts_notes_deterministic():
    from src.agent.tools.music.pattern_raw_tool import validate_notes
    out = validate_notes([
        {"pitch": 64, "start": 2, "dur": 1},
        {"pitch": 60, "start": 0, "dur": 1},
        {"pitch": 62, "start": 1, "dur": 1},
    ], 4)
    assert [n["step"] for n in out] == [0, 1, 2]


# ── Smoke: ground-truth pairs aus _neo4j_song_prompts ────────────────────────

def test_build_ground_truth_pairs_handles_songs_without_note_plan():
    from scripts._neo4j_song_prompts import build_ground_truth_pairs_from_songs
    songs = [{"title": "X", "artist": "Y", "bpm": 120, "key": "C", "note_plan": None}]
    assert build_ground_truth_pairs_from_songs(songs) == []


def test_build_ground_truth_pairs_produces_valid_tool_call():
    import json
    from scripts._neo4j_song_prompts import build_ground_truth_pairs_from_songs
    songs = [{
        "title": "Demo", "artist": "Tester", "bpm": 120, "key": "C minor",
        "note_plan": "Notenplan Demo (C minor, 120 BPM):\n  Bass (FM-4): C3=60 [s0,dur1]",
    }]
    pairs = build_ground_truth_pairs_from_songs(songs)
    assert len(pairs) == 1
    prompt, answer = pairs[0]
    assert "Demo" in prompt and "Tester" in prompt
    parsed = json.loads(answer)
    assert parsed["tool"] == "write_pattern_raw"
    assert parsed["args"]["notes"][0]["pitch"] == 60
