"""Hardcoded Fallback-Strategy — extrahiert aus pattern_generators._drums (B.2)."""
from __future__ import annotations
from src.agent.tools.music.pattern_generators import _drums


class HardcodedFallbackStrategy:
    """Statische Drum-Patterns pro Genre — Fallback wenn KB nichts liefert."""

    name = "hardcoded_fallback"

    def generate(self, genre: str, bars: int, style: str) -> list[dict]:
        return _drums(genre, bars, style)
