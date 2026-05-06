from __future__ import annotations
import operator
from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


def _merge_dicts(a: dict, b: dict) -> dict:
    """Reducer: letzter Schreiber gewinnt für slave_retry_counts."""
    return {**a, **b}


class BitwigTrack(TypedDict):
    index:      int
    instrument: str
    has_clips:  list[int]   # Slot-Indizes mit Clips


# ── Song-Kompositionsplan (wird vor erster OSC-Nachricht erstellt) ─────────────

class SongBlueprint(TypedDict):
    """Kompositionsplan: wird einmal geplant, dann Schritt für Schritt ausgeführt."""
    genre:       str
    bpm:         float
    sections:    list[str]            # Reihenfolge: ["intro", "verse", "chorus", ...]
    section_bars: dict[str, int]      # Länge je Section in Takten
    chord_map:   dict[str, list[str]] # Section → Akkordliste
    instrument_roles: list[str]       # Aktive Rollen (z.B. ["kick","bass","lead"])


class SectionResult(TypedDict):
    """Ergebnis einer fertig generierten Section."""
    section:     str
    slot_base:   int    # Clip-Slot-Startindex
    note_count:  int    # Gesamt-Noten dieser Section
    bpm:         float


# ── LangGraph Agent-State ─────────────────────────────────────────────────────

GenerationPhase = Literal[
    "idle",         # Noch nichts gestartet
    "planning",     # Blueprint wird erstellt
    "setup",        # Tracks + Instrumente werden angelegt
    "generating",   # Sections werden generiert
    "verifying",    # verify_song läuft
    "done",         # Fertig
    "error",        # Nicht behebbar
]


class AgentState(TypedDict):
    messages:      Annotated[list, add_messages]
    # Bitwig-Projektzustand
    track_count:   int
    tracks:        list[BitwigTrack]
    tempo:         float
    bridge_ok:     bool
    # Song-Generierungs-Kontext
    generation_phase:   GenerationPhase
    song_blueprint:     Optional[SongBlueprint]
    section_timeline:   list[SectionResult]    # bereits fertige Sections
    quality_report:     Optional[dict]          # letztes verify_song JSON
    pending_sections:   list[str]              # noch zu generierende Sections
    retry_count:        int
    # ── Multi-Agent Slave-State ───────────────────────────────────────────────
    slave_plan:          Optional[dict]                              # plan-Node Output: {instrument_hint, fx_hint, bpm, beat_count, scale}
    slave_results:       Annotated[list[dict], operator.add]        # Fan-in Reducer: sammelt Outputs aller Slaves
    assembled_json:      Optional[str]                              # assemble-Node: fertiges build_song JSON
    build_result:        Optional[str]                              # execute_build-Node: Tool-Rückgabe
    slave_retry_counts:  Annotated[dict, _merge_dicts]              # {"instrument": 0, "notes": 0}
