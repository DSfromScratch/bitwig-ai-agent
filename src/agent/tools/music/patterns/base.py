"""Strategy-Protocol für Drum-Pattern-Generierung (B.2 / F2+F9)."""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class DrumPatternStrategy(Protocol):
    """Erzeugt Drum-Noten für (genre, bars, style).

    Implementierungen:
    - KBDrumPatternStrategy: liest aus Neo4j Knowledge Base
    - HardcodedFallbackStrategy: statische Default-Patterns
    """

    name: str

    def generate(self, genre: str, bars: int, style: str) -> list[dict]:
        """Liefert Liste von {step, pitch, vel, dur}-Dicts oder leere Liste."""
        ...
