"""Backward-compatible music pattern helpers.

The test-suite and data-export paths still import these helpers from the legacy
module path. Keep the functions deterministic and lightweight so they can be
used without Neo4j or Bitwig.
"""
from __future__ import annotations

from collections.abc import Iterable

from .music_data import _root_midi


def _note(step: float, pitch: int, vel: float = 0.8, dur: float = 0.25) -> dict:
    return {"step": float(step), "pitch": int(pitch), "vel": float(vel), "dur": float(dur)}


def _repeat_steps(bars: int, values: Iterable[tuple[float, int, float, float]]) -> list[dict]:
    notes: list[dict] = []
    for bar in range(max(bars, 1)):
        offset = float(bar * 4)
        for step, pitch, vel, dur in values:
            notes.append(_note(offset + step, pitch, vel, dur))
    return notes


def _drums(genre: str, bars: int, style: str) -> list[dict]:
    genre_l = genre.lower()
    style_l = style.lower()

    if genre_l == "jazz":
        ride_vel = 0.55 if style_l == "basic" else 0.62
        snare_vel = 0.48 if style_l == "basic" else 0.55
        kick_vel = 0.45 if style_l == "basic" else 0.5
        notes = _repeat_steps(
            bars,
            [
                (0.0, 51, ride_vel, 0.25),
                (0.5, 51, ride_vel - 0.05, 0.25),
                (1.0, 38, snare_vel, 0.25),
                (1.0, 44, 0.42, 0.25),
                (1.5, 51, ride_vel - 0.05, 0.25),
                (2.0, 51, ride_vel, 0.25),
                (2.5, 51, ride_vel - 0.05, 0.25),
                (3.0, 38, snare_vel, 0.25),
                (3.0, 44, 0.42, 0.25),
                (3.5, 51, ride_vel - 0.05, 0.25),
                (0.0, 36, kick_vel, 0.25),
            ],
        )
        if style_l in {"full", "complex"}:
            notes.extend(_repeat_steps(bars, [(2.0, 36, kick_vel + 0.05, 0.25)]))
        return notes

    kick_pattern = [0.0, 2.0]
    if style_l in {"full", "complex"}:
        kick_pattern += [0.5, 2.5]

    notes = []
    for bar in range(max(bars, 1)):
        offset = float(bar * 4)
        for step in kick_pattern:
            notes.append(_note(offset + step, 36, 0.88 if step in {0.0, 2.0} else 0.76, 0.25))
        for step in (1.0, 3.0):
            notes.append(_note(offset + step, 38, 0.84, 0.25))
        hh_steps = [i * 0.5 for i in range(8)]
        for idx, step in enumerate(hh_steps):
            vel = 0.58 if idx % 2 == 0 else 0.46
            notes.append(_note(offset + step, 42, vel, 0.25))
    return notes


def _bass(genre: str, bars: int, root: int, style: str) -> list[dict]:
    genre_l = genre.lower()
    style_l = style.lower()
    fifth = min(root + 7, 72)
    octave = min(root + 12, 72)
    notes: list[dict] = []
    for bar in range(max(bars, 1)):
        offset = float(bar * 4)
        notes.append(_note(offset + 0.0, root, 0.84, 0.5))
        notes.append(_note(offset + 1.5, fifth if genre_l != "jazz" else root + 5, 0.74, 0.25))
        notes.append(_note(offset + 2.0, root, 0.82, 0.5))
        if style_l in {"full", "funk", "jazz"}:
            notes.append(_note(offset + 3.0, octave, 0.68, 0.25))
    return notes


def _chords(genre: str, bars: int, chords: list[str], style: str) -> list[dict]:
    style_l = style.lower()
    scale_roots = {
        "c": 60, "dm": 62, "d": 62, "em": 64, "e": 64,
        "f": 65, "g": 67, "am": 69, "a": 69,
        "bb": 70, "b": 71,
    }
    notes: list[dict] = []
    source = chords or ["C", "Am", "F", "G"]
    for bar in range(max(bars, 1)):
        chord = source[bar % len(source)]
        root_name = chord.strip().lower().replace("maj7", "").replace("m7", "m").replace("7", "")
        root = scale_roots.get(root_name, 60)
        third = root + (3 if "m" in chord.lower() and "maj" not in chord.lower() else 4)
        fifth = root + 7
        dur = 4.0 if style_l in {"sustained", "full"} else 1.0
        offset = float(bar * 4)
        notes.extend([
            _note(offset + 0.0, root, 0.72, dur),
            _note(offset + 0.0, third, 0.66, dur),
            _note(offset + 0.0, fifth, 0.68, dur),
        ])
        if style_l in {"arpeggio", "staccato"}:
            notes.extend([
                _note(offset + 1.0, root, 0.62, 0.5),
                _note(offset + 2.0, third, 0.60, 0.5),
                _note(offset + 3.0, fifth, 0.62, 0.5),
            ])
    return notes


def _melody(genre: str, bars: int, key: str, scale: str, style: str) -> list[dict]:
    root = _root_midi(key, octave=4)
    steps = [0, 2, 4, 7, 9, 7, 4, 2]
    notes: list[dict] = []
    for bar in range(max(bars, 1)):
        offset = float(bar * 4)
        for idx, interval in enumerate(steps):
            notes.append(_note(offset + idx * 0.5, root + interval, 0.58 + (idx % 2) * 0.08, 0.25))
    return notes


def _808_kick(step: float = 0.0, vel: float = 0.95, dur: float = 0.25) -> list[dict]:
    return [_note(step, 36, vel, dur)]


def _808_snare(step: float = 1.0, vel: float = 0.85, dur: float = 0.25) -> list[dict]:
    return [_note(step, 38, vel, dur)]
