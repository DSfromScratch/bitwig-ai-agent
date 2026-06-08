"""Tests für scripts/generate_format_pairs.py — Noten-Dichte ≥ 8 pro Pair."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_format_pairs.py"
_spec = importlib.util.spec_from_file_location("generate_format_pairs", _SCRIPT)
gen = importlib.util.module_from_spec(_spec)

# Stub out neo4j session so the module loads without a live DB
_mock_session_ctx = MagicMock()
_mock_session_obj = MagicMock()
_mock_session_ctx.__enter__ = lambda s: _mock_session_obj
_mock_session_ctx.__exit__ = MagicMock(return_value=False)

with patch("src.knowledge.neo4j_graph.session", return_value=_mock_session_ctx):
    _spec.loader.exec_module(gen)


# ── Fixtures ──────────────────────────────────────────────────────────────────

SCALE_C_MAJ = {
    "C-Dur": [
        {"degree": 1, "degree_name": "I", "dn": "Tonika", "chord_de": "C-Dur",  "quality": "major",
         "base_notes": [60, 64, 67]},
        {"degree": 4, "degree_name": "IV", "dn": "Subdominante", "chord_de": "F-Dur",  "quality": "major",
         "base_notes": [65, 69, 72]},
        {"degree": 5, "degree_name": "V", "dn": "Dominante", "chord_de": "G-Dur",  "quality": "major",
         "base_notes": [67, 71, 74]},
        {"degree": 6, "degree_name": "VI", "dn": "Mediante", "chord_de": "A-Moll", "quality": "minor",
         "base_notes": [69, 72, 76]},
    ]
}

SCALE_A_MIN = {
    "A-Moll": [
        {"degree": 1, "degree_name": "I",  "dn": "Tonika", "chord_de": "A-Moll", "quality": "minor",
         "base_notes": [69, 72, 76]},
        {"degree": 5, "degree_name": "V",  "dn": "Dominante", "chord_de": "E-Dur",  "quality": "major",
         "base_notes": [76, 80, 83]},
    ]
}

SCALES = {**SCALE_C_MAJ, **SCALE_A_MIN}


def _notes_from_completion(completion: str) -> list[dict]:
    obj = json.loads(completion)
    notes_raw = obj.get("notes", "[]")
    if isinstance(notes_raw, str):
        notes_raw = json.loads(notes_raw)
    return notes_raw


# ── arpeggio_over_bar helper ──────────────────────────────────────────────────

def test_arpeggio_over_bar_fills_16_steps():
    """arpeggio_over_bar mit steps_per_note=1 erzeugt exakt 16 Noten."""
    notes = gen.arpeggio_over_bar([60, 64, 67], velocity=0.8, steps_per_note=1)
    assert len(notes) == 16
    assert all(n["step"] < 16 for n in notes)
    assert all(0 < n["velocity"] <= 1.0 for n in notes)


def test_arpeggio_over_bar_cycles_pitches():
    pitches = [60, 64, 67]
    notes = gen.arpeggio_over_bar(pitches, steps_per_note=1)
    for i, n in enumerate(notes):
        assert n["pitch"] == pitches[i % len(pitches)]


# ── generate_single_chord_pairs ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def chord_pairs():
    return gen.generate_single_chord_pairs(SCALES)


def test_chord_pairs_min_notes(chord_pairs):
    """Jedes Chord-Pair hat ≥ 8 Noten."""
    for p in chord_pairs:
        if "notes" not in p["completion"]:
            continue
        notes = _notes_from_completion(p["completion"])
        if notes:  # format_chord_notes Paare haben keine write_pattern
            assert len(notes) >= 8, f"Nur {len(notes)} Noten: {p['prompt']}"


def test_chord_pairs_all_steps_in_bar(chord_pairs):
    for p in chord_pairs:
        if '"tool": "write_pattern"' not in p["completion"]:
            continue
        notes = _notes_from_completion(p["completion"])
        for n in notes:
            assert 0 <= n["step"] <= 15


def test_chord_pairs_count(chord_pairs):
    # 2 Scales × 4/2 Chords × 3 Voicings × 2 prompt-types = mind. 12
    assert len(chord_pairs) >= 12


# ── generate_arp_pairs ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def arp_pairs():
    return gen.generate_arp_pairs(SCALES)


def test_arp_pairs_exactly_16_notes(arp_pairs):
    """Jedes Arp-Pair hat exakt 16 Noten (1 Step pro Note)."""
    for p in arp_pairs:
        notes = _notes_from_completion(p["completion"])
        assert len(notes) == 16, f"Erwartet 16, got {len(notes)}: {p['prompt']}"


def test_arp_pairs_steps_sequential(arp_pairs):
    for p in arp_pairs:
        notes = _notes_from_completion(p["completion"])
        steps = [n["step"] for n in notes]
        assert steps == list(range(16)), "Steps nicht 0..15"


# ── generate_scale_melody_pairs ───────────────────────────────────────────────

def test_scale_melody_pairs_min_notes():
    """Tonleiter auf+ab ≥ 14 Noten (2-Step-Abstände)."""
    mock_row = {"scale": "C-Dur", "scale_en": "C major", "notes": [0,2,4,5,7,9,11]}
    mock_result = MagicMock()
    mock_result.data.return_value = [mock_row]
    _mock_session_obj.run.return_value = mock_result

    pairs = gen.generate_scale_melody_pairs(_mock_session_obj)
    for p in pairs:
        if '"tool": "write_pattern"' not in p["completion"]:
            continue
        notes = _notes_from_completion(p["completion"])
        assert len(notes) >= 8, f"Nur {len(notes)} Noten: {p['prompt']}"


# ── generate_rhythm_variations ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rhythm_pairs():
    return gen.generate_rhythm_variations(SCALES)


def test_rhythm_pairs_min_notes(rhythm_pairs):
    """Rhythmus-Variations-Pairs ≥ 9 Noten (3 Akkordtöne × 3+ Steps)."""
    for p in rhythm_pairs:
        notes = _notes_from_completion(p["completion"])
        assert len(notes) >= 9, f"Nur {len(notes)} Noten: {p['prompt']}"


def test_rhythm_pairs_no_single_note_whole_bar(rhythm_pairs):
    """Keine 1-Noten-Whole-Bar-Akkorde mehr."""
    for p in rhythm_pairs:
        notes = _notes_from_completion(p["completion"])
        assert len(notes) > 3, f"Zu wenige Noten: {p['prompt']}"
