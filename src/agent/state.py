from __future__ import annotations
from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


def _merge_dicts(a: dict, b: dict) -> dict:
    """Reducer: letzter Schreiber gewinnt für slave_retry_counts."""
    return {**a, **b}


def _aggregate_results_reducer(existing: list, new: list) -> list:
    """Reducer für slave_results: unterstützt Reset via __reset__-Sentinel.

    verify_node setzt [{"__reset__": True}] wenn ein Retry-Loop startet —
    dann wird die Liste geleert statt die alten Ergebnisse zu behalten.
    """
    if new and isinstance(new[0], dict) and new[0].get("__reset__"):
        return new[1:]  # Sentinel konsumieren, Rest (leer) übernehmen
    return existing + new


class BitwigTrack(TypedDict):
    index:      int
    instrument: str
    has_clips:  list[int]   # Slot-Indizes mit Clips


# ── Result-Objekt: kontextabhängiger Ausführungsplan ──────────────────────────
#
# Der LLM erstellt ein BitwigResult wenn eine Anfrage ≥2 Schritte erfordert.
# Der execute_result-Executor läuft die Steps einmal sequentiell ab — kein
# ad-hoc Tool-Calling, keine Retry-Schleifen.
#
# context_type steuert welche Felder in `target` erwartet werden:
#   "track"  → target: {track_index: int}
#   "song"   → target: {bpm: float, genre: str}
#   "object" → target: {type: str, ...}  (bestehendes Bitwig-Objekt)
#
# Step-Typen (type-Feld):
#   load_instrument  args: {track_index, name}
#   append_effect    args: {track_index, name}
#   set_param        args: {track_index, index, value}
#   set_param_named  args: {track_index, param_name, value}
#   set_send         args: {track_index, send_index, level}
#   setup_drum_machine args: {track_index, pads:[{pad|note, name, uuid?}]}
#   set_tempo        args: {bpm}
#   add_track        args: {track_type}   (instrument/audio/return)
#   select_track     args: {track_index}
#   play             args: {}
#   stop             args: {}

class ResultStep(TypedDict):
    type:   str             # Step-Typ (s.o.)
    args:   dict            # Tool-spezifische Parameter
    status: str             # "pending" | "done" | "error"
    note:   Optional[str]   # Optionale Begründung vom LLM


class BitwigResult(TypedDict):
    context_type:   str              # "track" | "song" | "object"
    target:         dict             # Was bearbeitet wird
    neo4j_context:  list             # Findings aus Knowledge Base
    steps:          list             # list[ResultStep] — Ausführungsplan
    summary:        Optional[str]    # Kurzbeschreibung was das Result darstellt


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

RetrySignal = Literal[
    "instrument_retry",  # instrument_slave nochmal ausführen
    "harmony_retry",     # harmony_slave nochmal ausführen
    "note_retry",        # note_slave nochmal ausführen
]


class AgentState(TypedDict):
    messages:      Annotated[list, add_messages]
    # Bitwig-Projektzustand
    track_count:   int
    tracks:        list[BitwigTrack]
    tempo:         float
    bridge_ok:     bool
    # Result-Objekt: aktueller Ausführungsplan (None wenn kein aktives Result)
    bitwig_result: Optional[BitwigResult]
    # Song-Generierungs-Kontext
    generation_phase:   GenerationPhase
    song_blueprint:     Optional[SongBlueprint]
    section_timeline:   list[SectionResult]    # bereits fertige Sections
    quality_report:     Optional[dict]          # letztes verify_song JSON
    pending_sections:   list[str]              # noch zu generierende Sections
    retry_count:        int
    ui_song_config:     Optional[dict]         # Strukturierte Song-Config aus Bitwig UI (OSC)
    # ── Multi-Agent Slave-State ───────────────────────────────────────────────
    slave_plan:          Optional[dict]                              # plan-Node Output: {instrument_hint, fx_hint, bpm, beat_count, scale}
    slave_results:       Annotated[list[dict], _aggregate_results_reducer]  # Fan-in Reducer: sammelt Outputs aller Slaves (reset-fähig)
    assembled_json:      Optional[str]                              # assemble-Node: fertiges build_song JSON
    build_result:        Optional[str]                              # execute_build-Node: Tool-Rückgabe
    slave_retry_counts:  Annotated[dict, _merge_dicts]              # {"instrument": 0, "notes": 0}
    # ── Observer / Retry-Loop ─────────────────────────────────────────────────
    retry_budget:        dict                                        # {"instrument": 2, "harmony": 2, "notes": 2}
    phase_quality_score: float                                       # 0.0–1.0 nach verify
    quality_thresholds:  dict                                        # {"overall": 0.75, "notes": 0.70}
    retry_signal:        Optional[str]                               # None | "instrument_retry" | "harmony_retry" | "note_retry"
