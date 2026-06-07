"""
BitwigProjectSnapshot — vollständiger Projekt-State, einmalig via OSC geladen.

Ersetzt die verstreuten scan_project() + hierarchy + scenes Aufrufe durch
einen einzigen /agent/project/full-snapshot OSC-Roundtrip.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SceneInfo:
    idx: int          # 1-basiert (wie Bitwig-API)
    name: str         # "Intro", "Raise", "Garage" …
    clip_count: int = 0


@dataclass
class TimelineSection:
    name: str           # Name des Cue Markers ("Intro", "Raise" …)
    beat: float         # Position in Beats (0-basiert)
    bar: float          # Position in Takten (1-basiert, 4/4)
    length_beats: float = 0.0   # Länge bis zum nächsten Marker (0 = letzter)


@dataclass
class ClipInfo:
    scene_idx: int    # Welche Szene (1-basiert)
    has_content: bool
    length_beats: float = 0.0


@dataclass
class TrackSnapshot:
    idx: int
    name: str
    is_group: bool
    devices: list[str]              # Geräte-Namen (Reihenfolge wie in Bitwig)
    clips: dict[int, ClipInfo] = field(default_factory=dict)  # scene_idx → ClipInfo
    role: Optional[str] = None      # "Kick", "Bass", … aus SoundRecipe (nachgeladen)
    parent_group: Optional[str] = None  # Name des übergeordneten Groups

    @property
    def instrument(self) -> Optional[str]:
        """Erstes Gerät = Instrument (konventionell)."""
        return self.devices[0] if self.devices else None

    @property
    def fx(self) -> list[str]:
        """Alle Geräte nach dem ersten = FX-Kette."""
        return self.devices[1:] if len(self.devices) > 1 else []

    def first_clip_with_notes(self) -> Optional[int]:
        """Gibt scene_idx des ersten Clips mit Inhalt zurück — O(1)."""
        return next(
            (s for s, c in sorted(self.clips.items()) if c.has_content),
            None,
        )

    def clips_with_notes(self) -> list[int]:
        """Alle scene_idx mit Clip-Inhalt, sortiert."""
        return [s for s, c in sorted(self.clips.items()) if c.has_content]


@dataclass
class BitwigProjectSnapshot:
    project_name: str
    tempo: float
    scenes: list[SceneInfo]
    tracks: list[TrackSnapshot]
    timeline: list[TimelineSection] = field(default_factory=list)
    loaded_at: float = field(default_factory=time.time)

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def timeline_section_at(self, beat: float) -> Optional[TimelineSection]:
        """Gibt die Sektion zurück die zum gegebenen Beat-Zeitpunkt aktiv ist."""
        active = None
        for sec in self.timeline:
            if sec.beat <= beat:
                active = sec
        return active

    def timeline_section_by_name(self, name: str) -> Optional[TimelineSection]:
        nl = name.lower()
        return next((s for s in self.timeline if s.name.lower() == nl), None)

    def scene_by_name(self, name: str) -> Optional[SceneInfo]:
        nl = name.lower()
        return next((s for s in self.scenes if s.name.lower() == nl), None)

    def scene_by_idx(self, idx: int) -> Optional[SceneInfo]:
        return next((s for s in self.scenes if s.idx == idx), None)

    def get_track(self, idx: int) -> Optional[TrackSnapshot]:
        return next((t for t in self.tracks if t.idx == idx), None)

    def tracks_in_group(self, group_name: str) -> list[TrackSnapshot]:
        return [t for t in self.tracks if t.parent_group == group_name]

    def group_tracks(self) -> list[TrackSnapshot]:
        return [t for t in self.tracks if t.is_group]

    def instrument_tracks(self) -> list[TrackSnapshot]:
        return [t for t in self.tracks if not t.is_group]

    # ── Factory: aus OSC-Antwort ───────────────────────────────────────────────

    @classmethod
    def from_raw(cls, project_name: str, raw_json: str) -> "BitwigProjectSnapshot":
        """Baut Snapshot aus /agent/project/full-snapshot JSON-Antwort."""
        data = json.loads(raw_json)

        scenes = [
            SceneInfo(
                idx=s["idx"],
                name=s.get("name", f"Scene {s['idx']}"),
                clip_count=s.get("clip_count", 0),
            )
            for s in data.get("scenes", [])
        ]

        tracks_raw = data.get("tracks", [])
        tracks = []
        # Gruppen-Zuordnung: Track gehört zur nächst-vorherigen Gruppe
        current_group: Optional[str] = None
        for t in tracks_raw:
            idx = t["idx"]
            is_group = t.get("is_group", False)
            if is_group:
                current_group = t["name"]

            # Clip-Slot-Content: slots[] = [true/false, ...] pro Scene-Slot
            clips: dict[int, ClipInfo] = {}
            for slot_idx, has_content in enumerate(t.get("slots", [])):
                scene_idx = slot_idx + 1  # 1-basiert wie Bitwig
                clips[scene_idx] = ClipInfo(
                    scene_idx=scene_idx,
                    has_content=bool(has_content),
                )

            ts = TrackSnapshot(
                idx=idx,
                name=t["name"],
                is_group=is_group,
                devices=t.get("devices", []),
                clips=clips,
                parent_group=current_group if not is_group else None,
            )
            tracks.append(ts)

        # Cue Markers → Timeline Sections (Länge aus Abstand zum nächsten Marker)
        raw_markers = data.get("cue_markers", [])
        timeline: list[TimelineSection] = []
        for i, m in enumerate(raw_markers):
            beat = float(m.get("beat", 0.0))
            next_beat = float(raw_markers[i + 1]["beat"]) if i + 1 < len(raw_markers) else 0.0
            length = next_beat - beat if next_beat > beat else 0.0
            timeline.append(TimelineSection(
                name=m.get("name", f"Section {i+1}"),
                beat=beat,
                bar=float(m.get("bar", beat / 4.0 + 1.0)),
                length_beats=length,
            ))

        return cls(
            project_name=project_name,
            tempo=float(data.get("tempo", 120.0)),
            scenes=scenes,
            tracks=tracks,
            timeline=timeline,
        )

    @classmethod
    def from_osc(cls, project_name: str) -> "BitwigProjectSnapshot":
        """Lädt Snapshot via OSC — 1 Roundtrip. Delegiert an query_project_snapshot()."""
        from src.agent.osc.project_scan import query_project_snapshot
        return query_project_snapshot(project_name)

    @classmethod
    def empty(cls, project_name: str = "empty") -> "BitwigProjectSnapshot":
        return cls(project_name=project_name, tempo=120.0, scenes=[], tracks=[])

    def __repr__(self) -> str:
        tl = f", {len(self.timeline)} timeline sections" if self.timeline else ""
        return (
            f"BitwigProjectSnapshot({self.project_name!r}, "
            f"{len(self.tracks)} tracks, "
            f"{len(self.scenes)} scenes{tl}, "
            f"{self.tempo} BPM)"
        )
