"""Unit Tests: Candidate-Scoring im NoteSlave."""
from src.agent.slaves.note_slave import _resolve_candidate_count, _score_notes


def _mk_notes(pitches, dur=0.5):
    return [
        {"step": i * 0.5, "pitch": p, "vel": 0.7 + (0.2 if i % 2 == 0 else 0.0), "dur": dur}
        for i, p in enumerate(pitches)
    ]


def test_candidate_count_defaults_for_riff(monkeypatch):
    monkeypatch.delenv("NOTE_SLAVE_CANDIDATES", raising=False)
    assert _resolve_candidate_count("Erstelle ein Rock-Riff") == 8


def test_candidate_count_env_override_clamped(monkeypatch):
    monkeypatch.setenv("NOTE_SLAVE_CANDIDATES", "99")
    assert _resolve_candidate_count("x") == 12


def test_score_prefers_variety_over_loop():
    harmony = {
        "allowed_pitch_classes": [2, 4, 7, 9, 11],
    }
    repetitive = _mk_notes([40, 43, 47, 40, 43, 47, 40, 43, 47, 40, 43, 47, 40, 43, 47, 40], dur=0.5)
    varied = [
        {"step": 0.0, "pitch": 43, "vel": 0.9, "dur": 0.5},
        {"step": 0.5, "pitch": 45, "vel": 0.7, "dur": 0.25},
        {"step": 1.0, "pitch": 47, "vel": 0.9, "dur": 0.5},
        {"step": 1.5, "pitch": 50, "vel": 0.68, "dur": 0.5},
        {"step": 2.0, "pitch": 43, "vel": 0.9, "dur": 0.5},
        {"step": 2.5, "pitch": 40, "vel": 0.66, "dur": 0.25},
        {"step": 3.0, "pitch": 47, "vel": 0.9, "dur": 1.0},
        {"step": 4.0, "pitch": 43, "vel": 0.94, "dur": 0.5},
    ]

    score_loop = _score_notes(repetitive, harmony, "Rock-Riff")
    score_varied = _score_notes(varied, harmony, "Rock-Riff")
    assert score_varied > score_loop
