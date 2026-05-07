import pytest

from src.audio.style_rules import (
    apply_dynamics,
    apply_register_hint,
    apply_rhythm_pattern,
    apply_technique,
)


def _notes():
    return [
        {"step": 0.0, "pitch": 64, "vel": 0.7, "dur": 0.5},
        {"step": 0.5, "pitch": 67, "vel": 0.7, "dur": 0.5},
        {"step": 1.0, "pitch": 71, "vel": 0.7, "dur": 0.5},
        {"step": 1.5, "pitch": 74, "vel": 0.7, "dur": 0.5},
    ]


@pytest.mark.unit
def test_apply_register_hint_low_clamps_pitches():
    out = apply_register_hint(_notes(), "Low (E2-D3)")
    assert all(40 <= int(n["pitch"]) <= 50 for n in out)


@pytest.mark.unit
def test_apply_rhythm_pattern_gallop_sets_triplet_grouping():
    out = apply_rhythm_pattern(_notes(), "Gallop")
    durs = [round(float(n["dur"]), 3) for n in out]
    assert durs[:3] == [0.25, 0.25, 0.5]


@pytest.mark.unit
def test_apply_technique_palm_mute_shortens_and_clamps():
    out = apply_technique(_notes(), "Palm Mute")
    assert all(float(n["dur"]) <= 0.25 for n in out)
    assert all(40 <= int(n["pitch"]) <= 52 for n in out)


@pytest.mark.unit
def test_apply_dynamics_accent_1_3_increases_downbeat_velocity():
    notes = [
        {"step": 0.0, "pitch": 50, "vel": 0.6, "dur": 0.5},
        {"step": 1.0, "pitch": 50, "vel": 0.6, "dur": 0.5},
        {"step": 2.0, "pitch": 50, "vel": 0.6, "dur": 0.5},
        {"step": 3.0, "pitch": 50, "vel": 0.6, "dur": 0.5},
    ]
    out = apply_dynamics(notes, "Accent 1&3")
    assert out[0]["vel"] > out[1]["vel"]
    assert out[2]["vel"] > out[3]["vel"]
