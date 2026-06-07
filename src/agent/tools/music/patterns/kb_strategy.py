"""KB-backed Drum-Pattern-Strategy — fragt Neo4j nach gelernten Patterns (B.2)."""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)


class KBDrumPatternStrategy:
    """Holt Drum-Pattern aus Knowledge-Base via rhythm_tool.

    Gibt leere Liste zurück wenn KB nichts kennt — Caller fällt dann auf
    HardcodedFallbackStrategy zurück.
    """

    name = "kb_drum_pattern"

    def generate(self, genre: str, bars: int, style: str) -> list[dict]:
        try:
            from src.agent.tools.rhythm_tool import rhythm_tool
        except ImportError as exc:
            log.debug("rhythm_tool nicht verfügbar: %s", exc)
            return []

        try:
            result = rhythm_tool.invoke({"genre": genre, "bars": bars})
        except (RuntimeError, ValueError, OSError) as exc:
            log.debug("rhythm_tool fehlgeschlagen für %s: %s", genre, exc)
            return []

        if isinstance(result, dict) and result.get("notes"):
            return list(result["notes"])
        if isinstance(result, list):
            return result
        return []
