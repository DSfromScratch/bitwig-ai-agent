"""
Musikalische Grunddaten: Tonartbezeichnungen.
"""
from __future__ import annotations

_NOTE_NAMES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

def _root_midi(key: str, octave: int = 3) -> int:
    note = key.rstrip("0123456789").replace(" ", "")
    return 12 * (octave + 1) + _NOTE_NAMES.get(note, 0)


