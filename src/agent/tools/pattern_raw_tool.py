"""Hybrid-Tool: LLM erzeugt Noten direkt (statt aus Python-Templates).

Verwendung sinnvoll, wenn:
  * Der User ein konkretes Riff / eine konkrete Melodie verlangt
    ("spiel das exakte Riff aus Da Funk, Takt 1-2")
  * Ein Song-Anker aus Neo4j note_plan-Daten hat (Ground-Truth-Training)
  * Der User explizite Note-Sequences durchgibt

Im Gegensatz zu write_pattern (deterministisch, Python-Templates) wird hier
die musikalische Substanz vom LLM gelernt. Schema-Validierung verhindert
unspielbare Noten (out-of-range pitch/velocity, negative dur, etc.).

Geschrieben wird über denselben compose_notes-Pfad wie write_pattern — die
einzige Differenz ist die Notenquelle.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


# ── Schema-Validierung ────────────────────────────────────────────────────────

MIN_PITCH, MAX_PITCH = 0, 127
MIN_VEL,   MAX_VEL   = 0.0, 1.0
MIN_DUR              = 0.0625  # 1/16 Beat = kürzest sinnvoll
MAX_LENGTH_BEATS     = 64


class NoteValidationError(ValueError):
    pass


def _normalize_note(raw: Any, idx: int) -> dict:
    """Akzeptiert flexibles Schema (vel als int 0-127 oder float 0-1, dur in beats),
    gibt kanonisches dict zurück. Wirft NoteValidationError bei Fehlern."""
    if not isinstance(raw, dict):
        raise NoteValidationError(f"Note {idx}: muss dict sein, ist {type(raw).__name__}")

    # Pitch
    pitch = raw.get("pitch")
    if pitch is None:
        raise NoteValidationError(f"Note {idx}: 'pitch' fehlt")
    try:
        pitch = int(pitch)
    except (TypeError, ValueError):
        raise NoteValidationError(f"Note {idx}: 'pitch' nicht numerisch ({pitch!r})")
    if not (MIN_PITCH <= pitch <= MAX_PITCH):
        raise NoteValidationError(f"Note {idx}: pitch={pitch} außerhalb 0-127")

    # Start (Beat-Offset)
    start = raw.get("start", raw.get("step", raw.get("time")))
    if start is None:
        raise NoteValidationError(f"Note {idx}: 'start' fehlt")
    try:
        start = float(start)
    except (TypeError, ValueError):
        raise NoteValidationError(f"Note {idx}: 'start' nicht numerisch ({start!r})")
    if start < 0:
        raise NoteValidationError(f"Note {idx}: start={start} negativ")

    # Dauer
    dur = raw.get("dur", raw.get("duration", raw.get("length")))
    if dur is None:
        raise NoteValidationError(f"Note {idx}: 'dur' fehlt")
    try:
        dur = float(dur)
    except (TypeError, ValueError):
        raise NoteValidationError(f"Note {idx}: 'dur' nicht numerisch ({dur!r})")
    if dur < MIN_DUR:
        raise NoteValidationError(f"Note {idx}: dur={dur} < {MIN_DUR} (zu kurz)")

    # Velocity (0-1 float ODER 0-127 int)
    vel = raw.get("vel", raw.get("velocity", 0.8))
    try:
        vel = float(vel)
    except (TypeError, ValueError):
        raise NoteValidationError(f"Note {idx}: 'vel' nicht numerisch ({vel!r})")
    if vel > 1.0:
        vel = vel / 127.0  # auto-convert int-MIDI-vel
    if not (MIN_VEL <= vel <= MAX_VEL):
        raise NoteValidationError(f"Note {idx}: vel={vel} außerhalb 0-1")

    return {"step": start, "pitch": pitch, "vel": round(vel, 3), "dur": dur}


def validate_notes(notes: list, length_beats: float) -> list[dict]:
    """Validiert + normalisiert eine komplette Notenliste."""
    if not isinstance(notes, list):
        raise NoteValidationError(f"notes muss list sein, ist {type(notes).__name__}")
    if not notes:
        raise NoteValidationError("notes ist leer — write_pattern_raw braucht ≥ 1 Note")
    if length_beats <= 0 or length_beats > MAX_LENGTH_BEATS:
        raise NoteValidationError(f"length_beats={length_beats} außerhalb (0, {MAX_LENGTH_BEATS}]")

    normalized = [_normalize_note(n, i) for i, n in enumerate(notes)]
    # Reihenfolge nach Start, dann Pitch (deterministisch)
    normalized.sort(key=lambda n: (n["step"], n["pitch"]))

    # Noten über length_beats hinaus abschneiden ist OK, aber warnen
    over = [n for n in normalized if n["step"] >= length_beats]
    if len(over) == len(normalized):
        raise NoteValidationError(
            f"ALLE {len(normalized)} Noten liegen jenseits length_beats={length_beats}"
        )

    return normalized


# ── Tool ──────────────────────────────────────────────────────────────────────

@tool
def write_pattern_raw(
    track_index: int,
    notes: list,
    length_beats: float = 8.0,
    slot: int = 0,
    instrument: str = "raw",
    bpm: int = 120,
    genre: str = "custom",
    key: str | None = None,
) -> str:
    """Schreibt eine vom LLM EXPLIZIT angegebene Notenfolge in einen Bitwig-Clip.

    Im Gegensatz zu write_pattern (deterministische Python-Templates) gibt
    das Modell hier die Noten als Liste direkt durch. Sinnvoll für:
      * Konkrete Riffs / Melodien aus Songreferenzen
      * Ground-Truth-Training mit Neo4j-Song-note_plan
      * User-Diktate ("spiel C-E-G-B als Akkord auf Beat 0")

    notes-Schema (jede Note ein dict):
        {"pitch": 0-127 (MIDI), "start": float (Beat-Offset),
         "dur": float (Beat-Länge, min 0.0625), "vel": 0.0-1.0}

    Beispiel notes=[{"pitch":60,"start":0,"dur":1,"vel":0.8},
                    {"pitch":64,"start":1,"dur":1,"vel":0.8}]

    length_beats: Clip-Länge (max 64 = 16 Takte 4/4)
    key:          Optional zur Reward-Bewertung (z.B. "C minor")
    """
    from src.bitwig_executor import compose_notes

    try:
        valid_notes = validate_notes(notes, length_beats)
    except NoteValidationError as e:
        return f"[write_pattern_raw] VALIDIERUNGSFEHLER: {e}"

    result = compose_notes({
        "context_type": "track",
        "target": {"bpm": bpm, "genre": genre},
        "track": {"index": track_index, "name": instrument, "instrument": instrument},
        "summary": f"{genre} raw-pattern ({len(valid_notes)} Noten, {length_beats} Beats)",
        "steps": [{
            "type": "write_notes",
            "args": {"track_index": track_index, "slot": slot,
                     "length_beats": length_beats, "notes": valid_notes},
            "status": "pending", "note": "",
        }],
    })

    # Optionale Reward-Hinweise direkt am Tool-Output (für Self-Refine + Training)
    extra = ""
    if key:
        try:
            from src.agent.tools.reward import key_conformance
            conf = key_conformance(valid_notes, key)
            extra = f" | key_conformance({key})={conf:.2f}"
        except Exception:
            pass

    return (f"[write_pattern_raw] {len(valid_notes)} Noten geschrieben "
            f"(len={length_beats}b){extra} | {result}")
