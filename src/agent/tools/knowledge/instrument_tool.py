"""get_instruments_for_song — Instrument-Auswahl via Neo4j KB (F10)."""
from __future__ import annotations

import json

from langchain_core.tools import tool


@tool
def get_instruments_for_song(
    genre: str,
    roles: list[str],
    mood: str = "",
    energy: float = 0.7,
) -> str:
    """Wählt passende Bitwig-Devices für jeden Track aus der Wissensdatenbank.

    Immer aufrufen bevor Tracks angelegt werden — niemals Device-Namen
    hardcoden oder aus internen Mappings nehmen.

    Das LLM soll anhand der zurückgegebenen Optionen und Beschreibungen
    begründet entscheiden, welches Device am besten zur Anfrage passt.

    Args:
        genre:  Musikgenre (rock, metal, jazz, pop, blues, electronic ...)
        roles:  Benötigte Rollen z.B. ["kick","snare","hihat","bass","chords","lead"]
        mood:   Stimmung (introspective, aggressive, warm, dark, driving ...)
        energy: Energie-Level 0.0–1.0 — beeinflusst default_velocity-Gewichtung
    """
    from src.knowledge.repositories import InstrumentRepository

    repo   = InstrumentRepository()
    result = {}

    for role in roles:
        options = repo.find(role=role, genre=genre, mood=mood, limit=3)
        if not options:
            result[role] = {
                "error": f"Kein Device für role='{role}' genre='{genre}' in KB"
            }
        else:
            result[role] = [
                {
                    "device_name":      opt.device_name,
                    "uuid":             opt.uuid,
                    "midi_range":       [opt.midi_low, opt.midi_high],
                    "default_velocity": opt.default_velocity,
                    "description":      opt.description,
                }
                for opt in options
            ]

    return json.dumps(result, indent=2, ensure_ascii=False)
