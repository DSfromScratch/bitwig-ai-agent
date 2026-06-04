"""
ProjectTemplate — deklarative Beschreibung einer Bitwig-Projekt-Struktur.

Template Pattern: beschreibt WAS ein Projekt enthalten soll.
Plugin Pattern:  TrackPlugin-Subklassen erzeugen die konkreten Steps.

Verwendung:
  # Aus bestehendem Projekt lernen
  snap = BitwigProjectSnapshot.from_osc("Chee - Hey Now")
  tmpl = ProjectTemplate.from_snapshot(snap)

  # Steps ableiten (nur was noch fehlt)
  steps = tmpl.to_steps(current_snapshot)

  # In Neo4j speichern
  ProjectTemplateRepository().save(tmpl)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.models.project_snapshot import BitwigProjectSnapshot
    from src.agent.models.steps import BitwigStep


TrackType = Literal["instrument", "audio", "return"]


@dataclass
class TemplateScene:
    name: str
    position: int  # 1-basiert


@dataclass
class TemplateTrack:
    name: str
    track_type: TrackType
    role: str                          # "Kick", "Bass", "Synth Lead" …
    instrument: Optional[str] = None   # Bitwig-Gerät oder VST-Name
    fx: list[str] = field(default_factory=list)
    # scene_name → notes [{step, pitch, vel, dur}]
    scene_clips: dict[str, list[dict]] = field(default_factory=dict)
    group: Optional[str] = None        # übergeordnete Gruppe (falls vorhanden)


@dataclass
class TemplateTimelineSection:
    name: str
    bar: float
    beat: float
    length_beats: float = 0.0


@dataclass
class ProjectTemplate:
    name: str
    tempo: float
    genre: str = "unknown"
    key: str = ""
    mode: str = ""                     # "major" | "minor"
    scenes: list[TemplateScene] = field(default_factory=list)
    # group_name → geordnete Track-Liste
    groups: dict[str, list[TemplateTrack]] = field(default_factory=dict)
    standalone_tracks: list[TemplateTrack] = field(default_factory=list)
    timeline: list[TemplateTimelineSection] = field(default_factory=list)
    description: str = ""

    # ── Hilfsmethoden ──────────────────────────────────────────────────────────

    def all_tracks(self) -> list[TemplateTrack]:
        """Alle Tracks in Reihenfolge: erst Gruppen-Tracks, dann standalone."""
        result: list[TemplateTrack] = []
        for tracks in self.groups.values():
            result.extend(tracks)
        result.extend(self.standalone_tracks)
        return result

    def scene_names(self) -> list[str]:
        return [s.name for s in self.scenes]

    def tracks_in_group(self, group: str) -> list[TemplateTrack]:
        return self.groups.get(group, [])

    # ── Factory: aus Snapshot ──────────────────────────────────────────────────

    @classmethod
    def from_snapshot(cls, snap: "BitwigProjectSnapshot",
                      genre: str = "unknown") -> "ProjectTemplate":
        """Reverse-Engineering: Live-Projekt → Template."""
        scenes = [
            TemplateScene(name=s.name, position=s.idx)
            for s in snap.scenes
            if s.name and not s.name.startswith("Scene ")
        ]

        groups: dict[str, list[TemplateTrack]] = {}
        standalone: list[TemplateTrack] = []

        for t in snap.instrument_tracks():
            tt = TemplateTrack(
                name=t.name,
                track_type="instrument",
                role=t.role or t.name,
                instrument=t.instrument,
                fx=t.fx,
                group=t.parent_group,
            )
            if t.parent_group:
                groups.setdefault(t.parent_group, []).append(tt)
            else:
                standalone.append(tt)

        timeline = [
            TemplateTimelineSection(
                name=sec.name,
                bar=sec.bar,
                beat=sec.beat,
                length_beats=sec.length_beats,
            )
            for sec in snap.timeline
        ]

        return cls(
            name=snap.project_name,
            tempo=snap.tempo,
            genre=genre,
            scenes=scenes,
            groups=groups,
            standalone_tracks=standalone,
            timeline=timeline,
        )

    # ── Step-Generierung (delegiert an Plugin-System) ─────────────────────────

    def to_steps(self,
                 current: Optional["BitwigProjectSnapshot"] = None,
                 include_notes: bool = False,
                 include_params: bool = False,
                 project: str = "",
                 ) -> list["BitwigStep"]:
        """
        Template → geordnete BitwigStep-Liste.

        Args:
            current:        Aktueller Projekt-State (diff — nur fehlende Tracks)
            include_notes:  write_notes Steps aus MidiClip.notes_json laden
            include_params: set_param Steps aus SoundRecipe.params_json laden
            project:        Projektname für Neo4j-Lookup (nötig für notes + params)
        """
        from src.agent.models.steps import SetTempoStep
        from src.agent.models.track_plugins import TRACK_PLUGINS

        steps: list["BitwigStep"] = [SetTempoStep(bpm=int(self.tempo))]

        existing_names: set[str] = set()
        if current:
            existing_names = {t.name for t in current.tracks}

        track_idx = 1
        if current:
            track_idx = len(current.tracks) + 1

        for track in self.all_tracks():
            if track.name in existing_names:
                continue

            plugin = TRACK_PLUGINS.get(track.track_type)
            if plugin:
                steps.extend(plugin.build_steps(track, track_idx))

            # Parameter aus Neo4j (set_param_named Steps)
            if include_params and project:
                steps.extend(_load_param_steps(track.name, track_idx, project))

            # Noten aus Neo4j (write_notes Steps, erste Szene)
            if include_notes and project:
                steps.extend(_load_note_steps(track.name, track_idx, project))

            track_idx += 1

        return steps

    # ── Serialisierung ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "tempo": self.tempo,
            "genre": self.genre,
            "key": self.key,
            "mode": self.mode,
            "description": self.description,
            "scenes": [{"name": s.name, "position": s.position} for s in self.scenes],
            "groups": {
                g: [_track_to_dict(t) for t in tracks]
                for g, tracks in self.groups.items()
            },
            "standalone_tracks": [_track_to_dict(t) for t in self.standalone_tracks],
            "timeline": [
                {"name": s.name, "bar": s.bar, "beat": s.beat, "length_beats": s.length_beats}
                for s in self.timeline
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectTemplate":
        scenes = [TemplateScene(**s) for s in d.get("scenes", [])]
        groups = {
            g: [TemplateTrack(**t) for t in tracks]
            for g, tracks in d.get("groups", {}).items()
        }
        standalone = [TemplateTrack(**t) for t in d.get("standalone_tracks", [])]
        timeline = [TemplateTimelineSection(**s) for s in d.get("timeline", [])]
        return cls(
            name=d["name"],
            tempo=float(d.get("tempo", 120)),
            genre=d.get("genre", "unknown"),
            key=d.get("key", ""),
            mode=d.get("mode", ""),
            description=d.get("description", ""),
            scenes=scenes,
            groups=groups,
            standalone_tracks=standalone,
            timeline=timeline,
        )

    def __repr__(self) -> str:
        n_tracks = len(self.all_tracks())
        return (
            f"ProjectTemplate({self.name!r}, {self.tempo} BPM, "
            f"{n_tracks} tracks, {len(self.scenes)} scenes)"
        )


def _load_param_steps(track_name: str, track_idx: int,
                      project: str) -> list["BitwigStep"]:
    """Lädt params_json aus SoundRecipe → set_param_named Steps."""
    import json as _json
    from src.agent.models.steps import SetParamNamedStep
    try:
        from src.knowledge.neo4j_graph import is_available, session
        if not is_available():
            return []
        with session() as s:
            row = s.run("""
                MATCH (sr:SoundRecipe {project: $proj})
                WHERE sr.track_name = $name AND sr.params_json IS NOT NULL
                RETURN sr.params_json AS pj LIMIT 1
            """, proj=project, name=track_name).single()
            if not row or not row["pj"]:
                return []
            pages = _json.loads(row["pj"])
            steps = []
            # Erste Seite reicht für die wichtigsten Remote Controls (8 params)
            first_page = pages[0] if isinstance(pages, list) and pages else {}
            params = first_page.get("params", pages) if isinstance(first_page, dict) else []
            for p in params[:8]:
                if isinstance(p, dict) and p.get("name") and p.get("value") is not None:
                    steps.append(SetParamNamedStep(
                        track_index=track_idx,
                        param_name=p["name"],
                        value=float(p["value"]),
                    ))
            return steps
    except Exception:
        return []


def _load_note_steps(track_name: str, track_idx: int,
                     project: str) -> list["BitwigStep"]:
    """Lädt notes_json aus MidiClip (erste Szene) → write_notes Step."""
    import json as _json
    from src.agent.models.steps import WriteNotesStep
    try:
        from src.knowledge.neo4j_graph import is_available, session
        if not is_available():
            return []
        with session() as s:
            row = s.run("""
                MATCH (mc:MidiClip {project: $proj})
                WHERE mc.track_name = $name AND mc.notes_json IS NOT NULL
                RETURN mc.notes_json AS nj, mc.loop_beats AS lb,
                       mc.scene_name AS scene
                ORDER BY mc.scene_idx
                LIMIT 1
            """, proj=project, name=track_name).single()
            if not row or not row["nj"]:
                return []
            notes = _json.loads(row["nj"])
            if not notes:
                return []
            return [WriteNotesStep(
                track_index=track_idx,
                notes=notes,
                length_beats=float(row["lb"] or 8.0),
                instrument=None,
            )]
    except Exception:
        return []


def _track_to_dict(t: TemplateTrack) -> dict:
    return {
        "name": t.name,
        "track_type": t.track_type,
        "role": t.role,
        "instrument": t.instrument,
        "fx": t.fx,
        "group": t.group,
        "scene_clips": {k: v for k, v in t.scene_clips.items()},
    }
