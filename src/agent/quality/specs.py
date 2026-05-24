"""Composite Quality Specification für Song-Verifikation (F3).

Jedes Qualitätskriterium ist eine eigenständige Spezifikation mit Gewicht.
CompositeQualitySpec kombiniert sie zu einem gewichteten Gesamtscore.
Neue Kriterien kosten ~10 Zeilen ohne Änderung am bestehenden Code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SongReport:
    track_count:      int
    expected_tracks:  int
    notes:            list[dict]   # [{pitch, velocity, step, duration}]
    scale_pcs:        set[int]     # Pitch-Classes der Tonart (0-11)
    bpm:              float
    expected_notes:   int


class QualitySpec(Protocol):
    weight: float
    def score(self, report: SongReport) -> float: ...
    def label(self) -> str: ...


class TrackCountSpec:
    weight = 0.20

    def score(self, r: SongReport) -> float:
        if r.expected_tracks <= 0:
            return 1.0
        return 1.0 if r.track_count >= r.expected_tracks else r.track_count / r.expected_tracks

    def label(self) -> str:
        return "track_count"


class NoteCountSpec:
    weight = 0.25

    def score(self, r: SongReport) -> float:
        return min(len(r.notes) / max(r.expected_notes, 1), 1.0)

    def label(self) -> str:
        return "note_count"


class ScaleConformanceSpec:
    weight = 0.30

    def score(self, r: SongReport) -> float:
        if not r.notes or not r.scale_pcs:
            return 1.0
        in_scale = sum(1 for n in r.notes if (int(n.get("pitch", 60)) % 12) in r.scale_pcs)
        return in_scale / len(r.notes)

    def label(self) -> str:
        return "scale_conformance"


class VelocityDistributionSpec:
    """Prüft ob Velocities musikalisch variiert sind (nicht alle gleich)."""
    weight = 0.15

    def score(self, r: SongReport) -> float:
        if len(r.notes) < 4:
            return 1.0
        vels = [float(n.get("velocity", n.get("vel", 0.8))) for n in r.notes]
        mean = sum(vels) / len(vels)
        variance = sum((v - mean) ** 2 for v in vels) / len(vels)
        std = variance ** 0.5
        return min(std / 0.15, 1.0)  # Ziel: stddev ≥ 0.15

    def label(self) -> str:
        return "velocity_distribution"


class DurationVarietySpec:
    weight = 0.10

    def score(self, r: SongReport) -> float:
        unique_dur = len({round(float(n.get("duration", n.get("dur", 0.5))), 2) for n in r.notes})
        return min(unique_dur / 3, 1.0)  # mind. 3 verschiedene Notenlängen

    def label(self) -> str:
        return "duration_variety"


@dataclass
class CompositeQualitySpec:
    specs: list = field(default_factory=list)

    def __post_init__(self) -> None:
        total_w = sum(s.weight for s in self.specs)
        self._norm = total_w or 1.0

    def evaluate(self, report: SongReport) -> tuple[float, dict[str, float]]:
        details = {s.label(): s.score(report) for s in self.specs}
        weighted = sum(details[s.label()] * s.weight for s in self.specs)
        return weighted / self._norm, details


# Standard-Instanz für verify_node
DEFAULT_QUALITY_SPEC = CompositeQualitySpec(specs=[
    TrackCountSpec(),
    NoteCountSpec(),
    ScaleConformanceSpec(),
    VelocityDistributionSpec(),
    DurationVarietySpec(),
])


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

_SCALE_PCS: dict[str, set[int]] = {
    "major":       {0, 2, 4, 5, 7, 9, 11},
    "minor":       {0, 2, 3, 5, 7, 8, 10},
    "pentatonic":  {0, 2, 4, 7, 9},
    "blues":       {0, 3, 5, 6, 7, 10},
    "dorian":      {0, 2, 3, 5, 7, 9, 10},
    "mixolydian":  {0, 2, 4, 5, 7, 9, 10},
}

_NOTE_ROOTS: dict[str, int] = {
    "c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3,
    "e": 4, "f": 5, "f#": 6, "gb": 6, "g": 7, "g#": 8,
    "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11,
}


def scale_pcs_from_hint(scale_hint: str) -> set[int]:
    """Konvertiert einen Scale-Hint-String in eine Menge von Pitch-Classes.

    Beispiele: "E minor" → {0,2,3,5,7,8,10} verschoben um 4 (E=4)
               "C major" → {0,2,4,5,7,9,11}
    """
    if not scale_hint:
        return set()
    lower = scale_hint.lower().strip()

    # Modus bestimmen
    mode_pcs: set[int] = set()
    for mode, pcs in _SCALE_PCS.items():
        if mode in lower:
            mode_pcs = pcs
            break
    if not mode_pcs:
        mode_pcs = _SCALE_PCS["minor"]  # Fallback

    # Grundton bestimmen
    root = 0
    for name, pc in sorted(_NOTE_ROOTS.items(), key=lambda x: -len(x[0])):
        if lower.startswith(name):
            root = pc
            break

    return {(pc + root) % 12 for pc in mode_pcs}
