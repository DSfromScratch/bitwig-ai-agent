"""
Musikalische Grunddaten: Akkorde, Skalen, Tonartbezeichnungen, Standard-Progressionen.
"""
from __future__ import annotations

# ── Chord Library ──────────────────────────────────────────────────────────────

_CHORDS: dict[str, list[int]] = {
    "C":      [60, 64, 67],  "Cm":     [60, 63, 67],
    "D":      [62, 66, 69],  "Dm":     [62, 65, 69],
    "E":      [64, 68, 71],  "Em":     [64, 67, 71],
    "F":      [65, 69, 72],  "Fm":     [65, 68, 72],
    "G":      [67, 71, 74],  "Gm":     [67, 70, 74],
    "A":      [69, 73, 76],  "Am":     [57, 60, 64],
    "Bb":     [58, 62, 65],  "Bbm":    [58, 61, 65],
    "B":      [59, 63, 66],  "Bm":     [59, 62, 66],
    "Cmaj7":  [60, 64, 67, 71],  "Dm7":    [62, 65, 69, 72],
    "Em7":    [64, 67, 71, 74],  "Fmaj7":  [65, 69, 72, 76],
    "G7":     [67, 71, 74, 77],  "Am7":    [57, 60, 64, 67],
    "Gmaj7":  [67, 71, 74, 78],  "Cmaj9":  [60, 64, 67, 71, 74],
}

_SCALES: dict[str, list[int]] = {
    "major":          [0, 2, 4, 5, 7, 9, 11],
    "minor":          [0, 2, 3, 5, 7, 8, 10],
    "natural minor":  [0, 2, 3, 5, 7, 8, 10],
    "pentatonic":     [0, 2, 4, 7, 9],
    "minor pentatonic": [0, 3, 5, 7, 10],
    "blues":          [0, 3, 5, 6, 7, 10],
    "dorian":         [0, 2, 3, 5, 7, 9, 10],
    "mixolydian":     [0, 2, 4, 5, 7, 9, 10],
}

_NOTE_NAMES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

_DEFAULT_PROGRESSIONS: dict[str, list[str]] = {
    "rock":    ["Am", "F",  "C",  "G"],
    "pop":     ["C",  "G",  "Am", "F"],
    "jazz":    ["Dm7", "G7", "Cmaj7", "Am7"],
    "hip-hop": ["Am", "G",  "Am", "G"],
    "hiphop":  ["Am", "G",  "Am", "G"],
    "trap":    ["Am", "G",  "Am", "G"],
    "dnb":     ["Am", "G"],
    "funk":    ["Am7", "Dm7", "Am7", "Dm7"],
    "blues":   ["A",  "A",  "D",  "A"],
    "default": ["C",  "Am", "F",  "G"],
}


def _root_midi(key: str, octave: int = 3) -> int:
    note = key.rstrip("0123456789").replace(" ", "")
    return 12 * (octave + 1) + _NOTE_NAMES.get(note, 0)


