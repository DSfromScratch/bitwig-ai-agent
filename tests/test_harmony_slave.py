import pytest

from src.agent.slaves.harmony_slave import run_harmony_slave


def _state(text: str, scale: str = ""):
    return {
        "slave_plan": {
            "user_text": text,
            "scale": scale,
            "instrument_hint": "Phase-4",
        },
        "slave_results": [],
        "slave_retry_counts": {},
    }


@pytest.mark.unit
def test_harmony_slave_rock_defaults_to_eminor_pentatonic():
    result = run_harmony_slave(_state("Erstelle ein Rock-Riff"))
    h = result["slave_results"][0]
    assert h["type"] == "harmony"
    assert h["scale_name"] == "minor_pentatonic"
    assert h["register_low"] <= 40 <= h["register_high"]


@pytest.mark.unit
def test_harmony_slave_detects_a_minor_from_prompt():
    result = run_harmony_slave(_state("A-Moll Melodie, 120 BPM"))
    h = result["slave_results"][0]
    assert h["key"].lower().startswith("a ")
    # A natural minor pitch classes: A B C D E F G -> 9,11,0,2,4,5,7
    assert set([9, 11, 0, 2, 4, 5, 7]).issuperset(set(h["allowed_pitch_classes"]))
