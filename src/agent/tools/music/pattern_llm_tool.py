"""LLM-gestützte Pattern-Generierung mit Neo4j-Theorie-Kontext."""
from __future__ import annotations

import json
import logging
import os

from langchain_core.tools import tool

from src.agent.tools.music.music_data import _root_midi
from src.agent.tools.music.pattern_raw_tool import validate_notes
import src.bitwig_executor as bitwig_executor

log = logging.getLogger("bitwig-agent")

_DRUM_MAP = (
    "GM MIDI drums: 36=Kick, 38=Snare, 42=HH-closed, 44=Pedal-HH, "
    "46=HH-open, 49=Crash, 51=Ride, 41=Low-Tom, 43=Mid-Tom, 45=Hi-Tom"
)

_SCALE_DEGREES = {
    "major":       [0, 2, 4, 5, 7, 9, 11],
    "minor":       [0, 2, 3, 5, 7, 8, 10],
    "dorian":      [0, 2, 3, 5, 7, 9, 10],
    "mixolydian":  [0, 2, 4, 5, 7, 9, 10],
    "pentatonic":  [0, 2, 4, 7, 9],
    "blues":       [0, 3, 5, 6, 7, 10],
}

_GENERATION_SYSTEM = """\
You are a MIDI pattern generator for Bitwig Studio.
Generate a {bars}-bar {genre} {instrument} pattern in {key} {scale} at {bpm} BPM.

Output ONLY a compact JSON array — no markdown, no explanation, just the raw JSON:
[{{"step": float, "pitch": int, "velocity": int, "dur": float}}, ...]

Field rules:
- step:     beat position (0.0 = bar 1 beat 1; max value = {max_beat:.2f})
- pitch:    MIDI note 0-127
- velocity: 40-127
- dur:      duration in beats (0.125=32nd, 0.25=16th, 0.5=8th, 1.0=quarter)

{hint}

Target density: {density} notes/bar. Use the theory context below.\
"""

_DENSITY = {
    "drum": 10, "bass": 6, "melody": 8, "chord": 4, "pad": 3,
}


def _instrument_type(instrument: str) -> str:
    name = instrument.lower()
    if any(t in name for t in ("drum", "kick", "snare", "hat", "vd-", "808", "perc")):
        return "drum"
    if any(t in name for t in ("bass", "sub", "vb-")):
        return "bass"
    if any(t in name for t in ("pad", "ambient", "texture", "atmo")):
        return "pad"
    if any(t in name for t in ("chord", "stab", "keys")):
        return "chord"
    return "melody"


def _scale_hint(key: str, scale: str) -> str:
    root = _root_midi(key, octave=4)
    intervals = _SCALE_DEGREES.get(scale.lower(), _SCALE_DEGREES["minor"])
    scale_pitches = sorted({(root + i) % 12 + 12 * ((root + i) // 12)
                             for i in intervals
                             for octave_offset in range(-12, 24, 12)
                             if 36 <= root + i + octave_offset <= 84})
    return f"Scale notes for {key} {scale}: {scale_pitches[:14]}"


def _fetch_theory_context(instrument: str, genre: str, key: str, scale: str) -> str:
    try:
        from src.agent.tools.knowledge.knowledge_tool import _query_neo4j
        result = _query_neo4j(f"{genre} {instrument} rhythm pattern {key} {scale}")
        if result:
            return result[:600] + " …" if len(result) > 600 else result
    except Exception as exc:
        log.debug("Theory context fetch failed: %s", exc)
    return ""


def _generate_notes_via_llm(
    instrument: str,
    genre: str,
    key: str,
    scale: str,
    bars: int,
    bpm: int,
    theory_context: str,
) -> list[dict] | None:
    """Ruft das LLM für MIDI-Noten-Generierung auf. Gibt None bei Fehler zurück."""
    from src.agent.llm_client import _get_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    itype = _instrument_type(instrument)
    is_drum = itype == "drum"
    hint = _DRUM_MAP if is_drum else _scale_hint(key, scale)
    length_beats = bars * 4

    system = _GENERATION_SYSTEM.format(
        bars=bars, genre=genre, instrument=instrument,
        key=key, scale=scale, bpm=bpm,
        max_beat=length_beats - 0.01,
        hint=hint,
        density=_DENSITY.get(itype, 6),
    )
    user = (
        f"Theory context:\n{theory_context}"
        if theory_context
        else f"Generate a {genre} {instrument} pattern."
    )

    try:
        llm = _get_llm(max_tokens=500, temperature=0.5)
        response = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        raw = (response.content or "").strip()

        # Strip markdown fences if present
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        # Find JSON array
        start_idx = raw.find("[")
        end_idx = raw.rfind("]") + 1
        if start_idx >= 0 and end_idx > start_idx:
            notes = json.loads(raw[start_idx:end_idx])
            if isinstance(notes, list) and notes:
                return notes
            log.warning("generate_pattern: LLM gab leere Noten-Liste zurück")
    except Exception as exc:
        log.warning("generate_pattern: LLM-Generierung fehlgeschlagen: %s", exc)
    return None


def _deterministic_fallback(instrument: str, genre: str, key: str, bars: int) -> list[dict]:
    from src.agent.tools.music.pattern_tools import _select_pattern
    notes = _select_pattern(instrument, genre, key, bars, "basic")
    # pattern_tools liefert {step, pitch, vel, dur} — validate_notes normalisiert das
    return notes


@tool
def generate_pattern(
    track_index: int,
    instrument: str,
    genre: str = "techno",
    key: str = "C",
    scale: str = "minor",
    bars: int = 2,
    bpm: int = 120,
) -> str:
    """Generiert ein musikalisches Pattern via LLM und schreibt es in einen Bitwig-Track.

    Holt Theorie-Kontext aus der Wissensdatenbank (Neo4j), lässt das LLM
    eine {step, pitch, velocity, dur}-Notenliste generieren, validiert sie
    und schreibt sie via BitwigStepPlugin (write_notes).

    Fällt automatisch auf deterministische Fallback-Patterns zurück wenn:
    - env FAST_PATTERN_MODE=1 gesetzt ist
    - LLM-Generierung fehlschlägt oder 0 gültige Noten liefert

    Args:
        track_index: Bitwig-Track-Index (1-basiert)
        instrument:  Instrument-Name (z.B. "drums", "bass", "melody", "vd-heavy")
        genre:       Musikgenre (z.B. "techno", "jazz", "house", "rock")
        key:         Tonart (z.B. "C", "F#", "Bb")
        scale:       Skala ("minor", "major", "dorian", "mixolydian", "pentatonic")
        bars:        Takte (Standard 2)
        bpm:         Tempo (Standard 120)
    """
    fast_mode = os.getenv("FAST_PATTERN_MODE", "0").strip() == "1"
    length_beats = float(bars * 4)
    notes: list[dict] = []
    source = "fallback"

    if not fast_mode:
        theory_context = _fetch_theory_context(instrument, genre, key, scale)
        raw = _generate_notes_via_llm(instrument, genre, key, scale, bars, bpm, theory_context)
        if raw:
            validated = validate_notes(raw, length_beats)
            if validated:
                notes = validated
                source = "llm"
                log.info(
                    "generate_pattern: LLM %d Noten für %s %s (%s %s)",
                    len(notes), genre, instrument, key, scale,
                )
            else:
                log.warning("generate_pattern: LLM-Noten ungültig nach Validierung — Fallback")
        else:
            log.warning("generate_pattern: LLM lieferte keine Noten — Fallback")

    if not notes:
        raw_fallback = _deterministic_fallback(instrument, genre, key, bars)
        notes = validate_notes(raw_fallback, length_beats)
        source = "fallback"
        log.info(
            "generate_pattern: Fallback %d Noten für %s %s",
            len(notes), genre, instrument,
        )

    payload = {
        "context_type": "song",
        "target": {
            "track_index": track_index,
            "instrument": instrument,
            "genre": genre,
            "bpm": bpm,
            "key": key,
        },
        "summary": f"generate_pattern [{source}] {instrument} {genre}",
        "steps": [
            {
                "type": "write_notes",
                "args": {
                    "track_index": track_index,
                    "notes": notes,
                    "length_beats": length_beats,
                    "instrument": instrument,
                },
                "status": "pending",
                "note": "",
            }
        ],
    }

    result = bitwig_executor.compose_notes(payload)
    return f"generate_pattern [{source}] {len(notes)} Noten | {result}"


__all__ = ["generate_pattern"]
