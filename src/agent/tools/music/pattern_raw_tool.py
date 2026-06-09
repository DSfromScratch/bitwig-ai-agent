"""Tool für das direkte Schreiben von MIDI-Noten in Bitwig."""
from __future__ import annotations

from langchain_core.tools import tool

import src.bitwig_executor as bitwig_executor


def validate_notes(notes: list[dict], length_beats: float) -> list[dict]:
    """Normalisiert und validiert Noten für den Bitwig-Executor.

    Akzeptiert zwei Eingabeformate und normalisiert auf das Executor-Format:
      - LLM-Format:   {pitch, step/start, dur/duration, velocity/vel}
      - Legacy-Format: {pitch, step, vel, dur}

    Ausgabe-Format: {step, pitch, velocity, dur}
      - step:     Beat-Position (float, Java: getOrDefault("step", 0.0))
      - pitch:    MIDI-Note (int, 0-127)
      - velocity: Velocity (int, 1-127, Java: direkte Verwendung)
      - dur:      Dauer in Beats (float > 0)
    """
    valid: list[dict] = []
    for note in notes or []:
        if not isinstance(note, dict):
            continue
        pitch = note.get("pitch")
        # Akzeptiere 'step' (legacy/executor) ODER 'start' (LLM-Ausgabe)
        step_raw = note.get("step") if note.get("step") is not None else note.get("start")
        # Akzeptiere 'dur' (kurz) ODER 'duration' (LLM-Ausgabe)
        dur_raw = note.get("dur") if note.get("dur") is not None else note.get("duration")

        if not isinstance(pitch, int) or not 0 <= pitch <= 127:
            continue
        if not isinstance(step_raw, (int, float)):
            continue
        if not isinstance(dur_raw, (int, float)) or float(dur_raw) <= 0:
            continue
        step = float(step_raw)
        if step < 0 or step >= float(length_beats):
            continue

        # Velocity normalisieren:
        # 'velocity' (int 0-127) → direkt
        # 'vel' (float 0.0-1.0) → *127
        vel_raw = note.get("velocity")
        if vel_raw is not None:
            vel = max(1, min(127, int(vel_raw)))
        else:
            vel_float = note.get("vel", 0.8)
            vel = max(1, min(127, int(float(vel_float) * 127)))

        valid.append({
            "step": step,
            "pitch": int(pitch),
            "velocity": vel,
            "dur": float(dur_raw),
        })
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
    """Schreibt MIDI-Noten direkt in einen Bitwig-Track via Step-Protokoll.

    Noten-Format (pro Note ein Dict):
      - step:     Beat-Position (0.0 = Takt 1 Beat 1; z.B. 2.0 = Beat 3)
      - pitch:    MIDI-Notennummer (0-127; Drums: 36=Kick, 38=Snare, 42=HH)
      - velocity: Anschlagstärke (1-127; alternativ 'vel' als 0.0-1.0)
      - dur:      Dauer in Beats (0.25 = 16tel, 0.5 = 8tel, 1.0 = Viertel)

    Args:
        track_index:  Bitwig-Track-Index (1-basiert)
        notes:        Notenliste
        length_beats: Länge des Clips in Beats (z.B. 8 für 2 Takte bei 4/4)
        instrument:   Name/Typ des Instruments (für Kontext-Logging)
        bpm:          Optionales Tempo-Override
        key:          Optionale Tonart (z.B. "C", "F#")
    """
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
