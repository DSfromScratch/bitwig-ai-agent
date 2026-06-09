"""Backward-compatible write_pattern tool."""
from __future__ import annotations

from langchain_core.tools import tool

import src.bitwig_executor as bitwig_executor

from .music_data import _root_midi
from .pattern_generators import _808_kick, _808_snare, _bass, _chords, _drums, _melody


def _select_pattern(instrument: str, genre: str, key: str, bars: int, style: str) -> list[dict]:
    name = instrument.lower()
    if any(token in name for token in ("vd-", "drum", "kick", "snare", "808")):
        return _drums(genre, bars, style)
    if any(token in name for token in ("vb-", "bass", "sub", "surge")):
        return _bass(genre, bars, _root_midi(key, octave=2), style)
    if any(token in name for token in ("vg-", "dexed", "ob-xd", "synth", "pad")):
        return _chords(genre, bars, ["C", "Am", "F", "G"], style)
    return _melody(genre, bars, key, "minor", style)


@tool
def write_pattern(
    track_index: int,
    instrument: str,
    genre: str = "rock",
    key: str = "C",
    scale: str = "minor",
    bars: int = 2,
    bpm: int = 120,
) -> str:
    """Generiert ein Pattern und schreibt es über den Bitwig-Executor."""
    style = "basic"
    notes = _select_pattern(instrument, genre, key, bars, style)

    payload = {
        "context_type": "song",
        "target": {"track_index": track_index, "instrument": instrument, "genre": genre},
        "summary": f"write_pattern {instrument} {genre}",
        "steps": [
            {
                "type": "write_notes",
                "args": {
                    "track_index": track_index,
                    "notes": notes,
                    "length_beats": bars * 4,
                    "instrument": instrument,
                },
                "status": "pending",
                "note": "",
            }
        ],
    }

    result = bitwig_executor.compose_notes(payload)
    return f"write_pattern | {result}"


__all__ = [
    "write_pattern",
    "_drums",
    "_bass",
    "_chords",
    "_melody",
    "_root_midi",
    "_808_kick",
    "_808_snare",
]