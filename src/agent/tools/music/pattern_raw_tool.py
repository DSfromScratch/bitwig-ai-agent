"""Compatibility tool for raw note writes."""
from __future__ import annotations

from langchain_core.tools import tool

import src.bitwig_executor as bitwig_executor


def validate_notes(notes: list[dict], length_beats: float) -> list[dict]:
    """Return only notes that fit the expected raw-note schema."""
    valid: list[dict] = []
    for note in notes or []:
        if not isinstance(note, dict):
            continue
        pitch = note.get("pitch")
        start = note.get("start")
        dur = note.get("dur")
        if not isinstance(pitch, int) or not 0 <= pitch <= 127:
            continue
        if not isinstance(start, (int, float)) or not isinstance(dur, (int, float)):
            continue
        if float(dur) <= 0:
            continue
        if float(start) < 0 or float(start) >= float(length_beats):
            continue
        valid.append(note)
    return valid


@tool
def write_pattern_raw(
    track_index: int,
    notes: list[dict],
    length_beats: float,
    instrument: str = "raw",
    bpm: int | None = None,
    key: str | None = None,
) -> str:
    """Write raw note data through the Bitwig executor."""
    payload = {
        "context_type": "song",
        "target": {"track_index": track_index, "instrument": instrument},
        "summary": f"write_pattern_raw {instrument}",
        "steps": [
            {
                "type": "write_notes",
                "args": {
                    "track_index": track_index,
                    "notes": validate_notes(notes, length_beats),
                    "length_beats": length_beats,
                    "instrument": instrument,
                },
                "status": "pending",
                "note": "",
            }
        ],
    }
    if bpm is not None:
        payload["target"]["bpm"] = bpm
    if key is not None:
        payload["target"]["key"] = key

    result = bitwig_executor.compose_notes(payload)
    return f"write_pattern_raw | {result}"


__all__ = ["validate_notes", "write_pattern_raw"]