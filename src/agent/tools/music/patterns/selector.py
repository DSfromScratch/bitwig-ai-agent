"""Strategy-Selektor: probiert KB zuerst, fällt auf Hardcoded zurück (B.2)."""
from __future__ import annotations
import logging

from src.agent.tools.music.patterns.base import DrumPatternStrategy
from src.agent.tools.music.patterns.kb_strategy import KBDrumPatternStrategy
from src.agent.tools.music.patterns.fallback import HardcodedFallbackStrategy

log = logging.getLogger(__name__)

_DEFAULT_CHAIN: list[DrumPatternStrategy] = [
    KBDrumPatternStrategy(),
    HardcodedFallbackStrategy(),
]


def generate_drums(genre: str, bars: int, style: str = "full") -> list[dict]:
    """Versucht Strategien in Reihenfolge KB → Hardcoded."""
    for strategy in _DEFAULT_CHAIN:
        notes = strategy.generate(genre, bars, style)
        if notes:
            log.debug("Drum-Pattern via %s (%d Noten)", strategy.name, len(notes))
            return notes
    return []
