"""Tests für Freesound-Genre-Ground-Truth: drum_notes_from_onsets +
build_genre_groundtruth_pairs (Anti-Runaway-Drum-GT für DPO).
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit


# ── drum_notes_from_onsets ───────────────────────────────────────────────────

def test_drum_notes_are_finite_within_one_bar():
    """Alle Noten müssen innerhalb 1 Takt (4 Beats) liegen — keine Runaways."""
    from scripts._neo4j_song_prompts import drum_notes_from_onsets

    notes = drum_notes_from_onsets([0, 2, 4, 6, 8, 10, 12, 14], energy=0.7)
    assert notes, "muss Noten erzeugen"
    assert all(n["start"] < 4.0 for n in notes), "alle Noten < 4 Beats"
    assert all(n["dur"] >= 0.0625 for n in notes), "dur über Minimum"


def test_drum_notes_contain_kick_snare_hat():
    from scripts._neo4j_song_prompts import drum_notes_from_onsets

    notes = drum_notes_from_onsets([0, 4, 8, 12], energy=0.6)
    pitches = {n["pitch"] for n in notes}
    assert 36 in pitches, "Kick (36) vorhanden"
    assert 38 in pitches, "Snare (38) vorhanden"
    assert 42 in pitches, "HiHat (42) vorhanden"


def test_drum_notes_kick_foundation_always_present():
    """Auch bei leeren Onsets bleibt das 4/4-Kick-Fundament {0,8} erhalten."""
    from scripts._neo4j_song_prompts import drum_notes_from_onsets

    notes = drum_notes_from_onsets([], energy=0.5)
    kick_starts = sorted(n["start"] for n in notes if n["pitch"] == 36)
    assert 0.0 in kick_starts          # step 0
    assert 2.0 in kick_starts          # step 8 = beat 2.0


def test_drum_notes_snare_on_backbeat():
    from scripts._neo4j_song_prompts import drum_notes_from_onsets

    notes = drum_notes_from_onsets([0, 8], energy=0.5)
    snare_starts = sorted(n["start"] for n in notes if n["pitch"] == 38)
    assert snare_starts == [1.0, 3.0]  # steps 4 & 12 → beats 1.0 & 3.0


def test_drum_notes_hat_density_scales_with_energy():
    from scripts._neo4j_song_prompts import drum_notes_from_onsets

    low = drum_notes_from_onsets(list(range(16)), energy=0.0)
    high = drum_notes_from_onsets(list(range(16)), energy=1.0)
    n_low = sum(1 for n in low if n["pitch"] == 42)
    n_high = sum(1 for n in high if n["pitch"] == 42)
    assert n_high > n_low, "höhere Energie → mehr HiHats"


def test_drum_notes_clamp_out_of_range_onsets():
    """Onsets außerhalb [0,15] werden ignoriert (kein Crash, finite)."""
    from scripts._neo4j_song_prompts import drum_notes_from_onsets

    notes = drum_notes_from_onsets([-3, 0, 8, 20, 99], energy=0.5)
    assert all(0.0 <= n["start"] < 4.0 for n in notes)


# ── build_genre_groundtruth_pairs ────────────────────────────────────────────

def test_build_genre_gt_pairs_shape():
    from scripts._neo4j_song_prompts import build_genre_groundtruth_pairs

    genres = [{"name": "Techno", "bpm": 130, "energy": 0.8,
               "onset_steps": [0, 2, 4, 6, 8, 10, 12, 14]}]
    pairs = build_genre_groundtruth_pairs(genres, max_per_genre=1)
    assert len(pairs) == 1
    prompt, gt_json = pairs[0]
    assert "Techno" in prompt
    call = json.loads(gt_json)
    assert call["tool"] == "write_pattern_raw"
    assert call["args"]["length_beats"] == 4.0
    assert call["args"]["track_index"] == 0
    assert len(call["args"]["notes"]) > 0


def test_build_genre_gt_pairs_no_melodic_key():
    """Drums sind atonal → kein 'key'-Arg (hält key_conformance neutral)."""
    from scripts._neo4j_song_prompts import build_genre_groundtruth_pairs

    genres = [{"name": "House", "bpm": 124, "energy": 0.6,
               "onset_steps": [0, 4, 8, 12]}]
    _, gt_json = build_genre_groundtruth_pairs(genres)[0]
    call = json.loads(gt_json)
    assert "key" not in call["args"]


def test_build_genre_gt_pairs_scores_high():
    """GT-Pair muss im Reward-System hoch scoren (>= 0.8)."""
    from scripts._neo4j_song_prompts import build_genre_groundtruth_pairs
    from src.agent.tools.music.reward import score_completion

    genres = [{"name": "Funk", "bpm": 105, "energy": 0.7,
               "onset_steps": [0, 3, 4, 7, 8, 11, 12, 15]}]
    prompt, gt_json = build_genre_groundtruth_pairs(genres)[0]
    score, _ = score_completion(prompt, gt_json)
    assert score >= 0.8, f"GT-Score zu niedrig: {score}"


def test_build_genre_gt_pairs_validates_with_pattern_raw():
    """Erzeugte Noten müssen validate_notes() bestehen."""
    from scripts._neo4j_song_prompts import build_genre_groundtruth_pairs
    from src.agent.tools.music.pattern_raw_tool import validate_notes

    genres = [{"name": "Trap", "bpm": 140, "energy": 0.5,
               "onset_steps": [0, 2, 6, 8, 10, 14]}]
    _, gt_json = build_genre_groundtruth_pairs(genres)[0]
    call = json.loads(gt_json)
    valid = validate_notes(call["args"]["notes"], call["args"]["length_beats"])
    assert len(valid) == len(call["args"]["notes"])


def test_build_genre_gt_pairs_empty_when_no_genres():
    from scripts._neo4j_song_prompts import build_genre_groundtruth_pairs

    assert build_genre_groundtruth_pairs([]) == []
