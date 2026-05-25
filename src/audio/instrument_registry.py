"""
Instrument Registry — MIDI-Bereiche und Default-Velocities je Rolle.

Wird vom Assemble-Node für Note-Clamping verwendet.
Instrument-Auswahl erfolgt dynamisch durch den InstrumentSlave (LLM).
"""
from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict


class InstrumentTemplate(TypedDict):
    role:             str
    midi_low:         int
    midi_high:        int
    default_velocity: float
    osc_track_index:  Optional[int]


DEFAULT_REGISTRY: dict[str, InstrumentTemplate] = {
    "kick":   {"role": "kick",   "midi_low": 36, "midi_high": 36, "default_velocity": 0.88, "osc_track_index": None},
    "snare":  {"role": "snare",  "midi_low": 38, "midi_high": 38, "default_velocity": 0.82, "osc_track_index": None},
    "hihat":  {"role": "hihat",  "midi_low": 42, "midi_high": 42, "default_velocity": 0.55, "osc_track_index": None},
    "bass":   {"role": "bass",   "midi_low": 28, "midi_high": 52, "default_velocity": 0.85, "osc_track_index": None},
    "chords": {"role": "chords", "midi_low": 48, "midi_high": 72, "default_velocity": 0.65, "osc_track_index": None},
    "lead":   {"role": "lead",   "midi_low": 55, "midi_high": 84, "default_velocity": 0.72, "osc_track_index": None},
    "pad":    {"role": "pad",    "midi_low": 48, "midi_high": 72, "default_velocity": 0.45, "osc_track_index": None},
    "melody": {"role": "melody", "midi_low": 55, "midi_high": 84, "default_velocity": 0.72, "osc_track_index": None},
}


def get_instrument(role: str) -> InstrumentTemplate:
    """Gibt MIDI-Bereich und Default-Velocity für eine Rolle zurück.

    Raises:
        KeyError: Wenn role nicht bekannt ist.
    """
    return dict(DEFAULT_REGISTRY[role])  # type: ignore[return-value]
