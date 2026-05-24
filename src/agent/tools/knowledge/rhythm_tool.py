"""get_rhythm_pattern — Drum-Pattern aus Neo4j KB (F9)."""
from __future__ import annotations

import json

from langchain_core.tools import tool


@tool
def get_rhythm_pattern(
    genre: str,
    section: str,
    energy: float = 0.7,
    mood: str = "",
) -> str:
    """Liest ein Drum-Pattern aus der Wissensdatenbank.

    Immer aufrufen bevor Drum-Noten geschrieben werden — nie hardcodierte
    Werte (36/38/42) oder eigene Patterns verwenden.

    Args:
        genre:   Musikgenre (rock, metal, jazz, pop, blues, trap, bossa nova ...)
        section: Song-Abschnitt (intro, verse, chorus, solo, outro)
        energy:  Energie-Level 0.0–1.0 (0.3 = ruhig, 0.9 = aggressiv)
        mood:    Optionale Stimmung (introspective, aggressive, driving ...)
    """
    from src.knowledge.repositories import DrumPatternRepository, DrumSoundRepository

    repo   = DrumPatternRepository()
    sounds = DrumSoundRepository()

    rec = repo.find(genre=genre, section=section, energy_max=energy, mood=mood)
    if rec is None:
        return (
            f"Kein Pattern für genre='{genre}' section='{section}' energy<={energy} in KB. "
            "Bitte energy, mood oder genre anpassen."
        )

    return json.dumps(
        {
            "description":  rec.description,
            "energy":       rec.energy,
            "kick_beats":   rec.kick_beats,
            "snare_beats":  rec.snare_beats,
            "hat_step":     rec.hat_step,
            "velocities": {
                "kick":    rec.kick_vel,
                "snare":   rec.snare_vel,
                "hat_on":  rec.hat_vel_on,
                "hat_off": rec.hat_vel_off,
            },
            "midi_pitches": {
                "kick":       sounds.pitch("kick"),
                "snare":      sounds.pitch("snare"),
                "closed_hat": sounds.pitch("closed_hat"),
                "open_hat":   sounds.pitch("open_hat"),
                "crash":      sounds.pitch("crash"),
            },
        },
        indent=2,
        ensure_ascii=False,
    )
