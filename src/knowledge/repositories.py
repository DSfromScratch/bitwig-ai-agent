"""Repository Pattern für KB-Zugriff (F9 + F10).

DrumPatternRepository  — liest DrumPattern-Nodes aus Neo4j (ersetzt DRUM_PROFILES-Dict)
DrumSoundRepository    — liest GM-Pitch-Mapping aus DrumSound-Nodes
InstrumentRepository   — liest InstrumentTemplate-Nodes für Instrument-Auswahl
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.knowledge.neo4j_graph import is_available, session

log = logging.getLogger("bitwig-agent.repositories")


# ── DrumPattern ───────────────────────────────────────────────────────────────

@dataclass
class DrumPatternRecord:
    kick_beats:  list[float] | str
    snare_beats: list[float]
    hat_step:    float
    hat_vel_on:  float
    hat_vel_off: float
    kick_vel:    float
    snare_vel:   float
    energy:      float
    description: str


class DrumPatternRepository:
    def find(
        self,
        genre: str,
        section: str,
        energy_max: float = 1.0,
        mood: str = "",
    ) -> DrumPatternRecord | None:
        """Gibt das passendste DrumPattern für genre + section zurück, oder None."""
        if not is_available():
            log.debug("Neo4j nicht verfügbar — DrumPatternRepository gibt None zurück")
            return None
        try:
            with session() as s:
                result = s.run(
                    """
                    MATCH (p:DrumPattern)
                    WHERE toLower(p.genre)   = toLower($genre)
                      AND toLower(p.section) = toLower($section)
                      AND p.energy           <= $energy_max
                      AND ($mood = '' OR toLower(p.mood) CONTAINS toLower($mood))
                    RETURN p
                    ORDER BY abs(p.energy - $energy_max)
                    LIMIT 1
                    """,
                    genre=genre,
                    section=section,
                    energy_max=energy_max,
                    mood=mood,
                )
                row = result.single()
                if row is None:
                    return None
                p = row["p"]
                return DrumPatternRecord(
                    kick_beats=list(p["kick_beats"]) if isinstance(p["kick_beats"], list) else p["kick_beats"],
                    snare_beats=list(p["snare_beats"]),
                    hat_step=float(p["hat_step"]),
                    hat_vel_on=float(p["hat_vel_on"]),
                    hat_vel_off=float(p["hat_vel_off"]),
                    kick_vel=float(p["kick_vel"]),
                    snare_vel=float(p["snare_vel"]),
                    energy=float(p["energy"]),
                    description=str(p.get("description", "")),
                )
        except Exception as exc:
            log.warning("DrumPatternRepository.find fehlgeschlagen: %s", exc)
            return None


# ── DrumSound ─────────────────────────────────────────────────────────────────

_GM_FALLBACK: dict[str, int] = {
    "kick": 36, "snare": 38, "closed_hat": 42,
    "open_hat": 46, "crash": 49,
}


class DrumSoundRepository:
    _cache: dict[str, int] = {}

    def pitch(self, sound_name: str) -> int:
        """Gibt den GM-MIDI-Pitch für sound_name zurück. Fällt auf Tabelle zurück."""
        if sound_name in self._cache:
            return self._cache[sound_name]

        if is_available():
            try:
                with session() as s:
                    row = s.run(
                        "MATCH (d:DrumSound {name: $n}) RETURN d.gm_pitch AS p",
                        n=sound_name,
                    ).single()
                    if row:
                        self._cache[sound_name] = int(row["p"])
                        return self._cache[sound_name]
            except Exception as exc:
                log.warning("DrumSoundRepository.pitch fehlgeschlagen: %s", exc)

        return _GM_FALLBACK.get(sound_name, 38)


# ── InstrumentTemplate ────────────────────────────────────────────────────────

@dataclass
class InstrumentRecord:
    role:             str
    device_name:      str
    uuid:             Optional[str]
    midi_low:         int
    midi_high:        int
    default_velocity: float
    description:      str


class InstrumentRepository:
    def find(
        self,
        role: str,
        genre: str,
        mood: str = "",
        limit: int = 3,
    ) -> list[InstrumentRecord]:
        """Gibt bis zu `limit` passende Devices für Rolle + Genre zurück."""
        if not is_available():
            log.debug("Neo4j nicht verfügbar — InstrumentRepository gibt [] zurück")
            return []
        try:
            with session() as s:
                result = s.run(
                    """
                    MATCH (t:InstrumentTemplate {role: $role})
                    WHERE ($genre = '' OR $genre IN t.genres)
                      AND NOT ($genre IN coalesce(t.not_for, []))
                      AND ($mood = '' OR $mood IN coalesce(t.moods, []))
                    RETURN t
                    ORDER BY
                        CASE WHEN $genre IN t.genres THEN 0 ELSE 1 END,
                        t.default_velocity DESC
                    LIMIT $limit
                    """,
                    role=role,
                    genre=genre.lower(),
                    mood=mood.lower(),
                    limit=limit,
                )
                return [
                    InstrumentRecord(
                        role=str(row["t"]["role"]),
                        device_name=str(row["t"]["device_name"]),
                        uuid=row["t"].get("uuid"),
                        midi_low=int(row["t"]["midi_low"]),
                        midi_high=int(row["t"]["midi_high"]),
                        default_velocity=float(row["t"]["default_velocity"]),
                        description=str(row["t"].get("description", "")),
                    )
                    for row in result
                ]
        except Exception as exc:
            log.warning("InstrumentRepository.find fehlgeschlagen: %s", exc)
            return []

    def find_best(self, role: str, genre: str, mood: str = "") -> InstrumentRecord | None:
        results = self.find(role, genre, mood, limit=1)
        return results[0] if results else None
