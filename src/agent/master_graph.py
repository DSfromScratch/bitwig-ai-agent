"""Master-Graph — LangGraph StateGraph mit parallelen Slave-Nodes via Send-API.

Architektur:
    plan → [Send(instrument_slave), Send(harmony_slave)] → note_slave → assemble → execute_build → verify → END

InstrumentSlave und NoteSlave laufen echt parallel via LangGraph Send-API.
Assemble merged die Fan-in Ergebnisse und baut das build_song JSON.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any

# ── Persistentes Logging in Datei ────────────────────────────────────────────
def _setup_file_logging() -> None:
    """Fügt einen FileHandler hinzu, falls noch keiner aktiv ist."""
    root = logging.getLogger()
    if any(isinstance(h, logging.FileHandler) for h in root.handlers):
        return
    log_dir = os.path.expanduser("~/bitwig-agent/logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"agent_{datetime.now().strftime('%Y%m%d')}.log")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))
    root.addHandler(fh)

_setup_file_logging()

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send

from src.agent.state import AgentState
from src.agent.policy import (
    is_concrete_track_task,
    _extract_explicit_fx,
    _extract_bpm,
    _extract_beats,
    _beats_from_time,
)
from src.agent.slaves.instrument_slave import run_instrument_slave
from src.agent.slaves.note_slave import run_note_slave
from src.agent.slaves.harmony_slave import run_harmony_slave
from src.agent.slaves.assemble import assemble_node

log = logging.getLogger("bitwig-agent.master-graph")

_MAX_SLAVE_RETRIES = 3

# ── Instrument-Hint extrahieren ───────────────────────────────────────────────

_INSTRUMENT_KEYWORDS = {
    "phase-4": "Phase-4",
    "phase4": "Phase-4",
    "fm-4": "FM-4",
    "fm4": "FM-4",
    "polysynth": "Polysynth",
    "surge": "Surge XT",
    "organ": "Organ",
    "sampler": "Sampler",
    "guitar": "Phase-4",    # Gitarre → Phase-4 als Default
    "gitarre": "Phase-4",
    "bass": "Polysynth",
    "lead": "FM-4",
}

_SCALE_KEYWORDS = [
    "pentatonik", "pentatonic", "minor", "moll", "major", "dur",
    "blues", "dorian", "mixolydian", "chromatic",
]


def _extract_instrument_hint(text: str) -> str:
    lower = text.lower()
    for key, name in _INSTRUMENT_KEYWORDS.items():
        if key in lower:
            return name
    return ""


def _extract_scale_hint(text: str) -> str:
    lower = text.lower()
    for kw in _SCALE_KEYWORDS:
        if kw in lower:
            # Kontext: "E-Moll-Pentatonik" → ganzen Begriff zurückgeben
            idx = lower.find(kw)
            start = max(0, idx - 10)
            end = min(len(text), idx + len(kw) + 10)
            return text[start:end].strip()
    return ""


# ── Nodes ─────────────────────────────────────────────────────────────────────

def plan_node(state: AgentState) -> dict:
    """Liest den User-Prompt, extrahiert Hinweise und legt slave_plan fest."""
    messages = state.get("messages") or []
    ui_cfg = state.get("ui_song_config") or {}
    user_text = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_text = (m.content or "").strip()
            if user_text:
                break

    cfg_genre = str(ui_cfg.get("genre", "")).strip()
    cfg_bpm = ui_cfg.get("bpm")
    cfg_beats = ui_cfg.get("length_beats")
    cfg_tracks = ui_cfg.get("track_count")
    cfg_key = str(ui_cfg.get("key", "")).strip()
    cfg_technique = str(ui_cfg.get("technique", "")).strip()
    cfg_rhythm = str(ui_cfg.get("rhythm_pattern", "")).strip()
    cfg_register = str(ui_cfg.get("string_register", "")).strip()
    cfg_dynamics = str(ui_cfg.get("dynamics_shape", "")).strip()
    cfg_fx = str(ui_cfg.get("fx_preset", "")).strip()

    if ui_cfg:
        cfg_text = (
            f"Genre {cfg_genre or 'Rock'}, {cfg_bpm or 120} BPM, "
            f"{cfg_tracks or 4} Track(s), Key {cfg_key or 'E minor'}, "
            f"{cfg_beats or 32} Beats, Technik {cfg_technique or 'Standard'}, "
            f"Rhythmus {cfg_rhythm or 'Straight Eighths'}, "
            f"Register {cfg_register or 'Low (E2-D3)'}, "
            f"Dynamik {cfg_dynamics or 'Accent 1&3'}, FX {cfg_fx or 'Distortion+Amp'}"
        )
        user_text = f"{user_text}\n\n[UI_CONFIG] {cfg_text}".strip()

    bpm = float(cfg_bpm) if cfg_bpm is not None else _extract_bpm(user_text, 120.0)
    beat_count = float(cfg_beats) if cfg_beats is not None else (_extract_beats(user_text) or _beats_from_time(bpm, user_text) or 16.0)
    instrument_hint = _extract_instrument_hint(user_text)
    fx_hint = cfg_fx if cfg_fx else ", ".join(_extract_explicit_fx(user_text))
    scale = cfg_key if cfg_key else _extract_scale_hint(user_text)

    slave_plan = {
        "user_text": user_text,
        "bpm": bpm,
        "beat_count": beat_count,
        "instrument_hint": instrument_hint,
        "fx_hint": fx_hint,
        "scale": scale,
        "genre": cfg_genre,
        "track_count": int(float(cfg_tracks)) if cfg_tracks is not None and str(cfg_tracks).strip() else 1,
        "technique": cfg_technique,
        "rhythm_pattern": cfg_rhythm,
        "string_register": cfg_register,
        "dynamics_shape": cfg_dynamics,
    }
    log.info(
        "Plan: bpm=%.0f, beats=%.0f, instrument=%s, fx=%s, scale=%s, technique=%s, rhythm=%s",
        bpm, beat_count, instrument_hint or "(auto)", fx_hint or "(auto)", scale or "(auto)",
        cfg_technique or "(auto)", cfg_rhythm or "(auto)",
    )
    return {
        "slave_plan": slave_plan,
        "slave_results": [],           # Reset: Fan-in Reducer beginnt leer
        "slave_retry_counts": {},
        "assembled_json": None,
        "build_result": None,
        "generation_phase": "planning",
    }


def execute_build_node(state: AgentState) -> dict:
    """Ruft build_song mit dem assemblierten JSON auf."""
    assembled = state.get("assembled_json")
    if not assembled:
        log.error("execute_build: kein assembled_json vorhanden")
        return {"build_result": None, "generation_phase": "error"}

    try:
        from src.agent.tools.song_tools import build_song
        log.info("execute_build: build_song aufrufen (%d Bytes JSON)", len(assembled))
        result = build_song.invoke({"project_json": assembled})
        log.info("execute_build: %s", str(result)[:200])
        return {"build_result": str(result), "generation_phase": "verifying"}
    except Exception as exc:
        log.error("execute_build: Fehler: %s", exc)
        return {"build_result": f"Fehler: {exc}", "generation_phase": "error"}


def _compute_quality(report: dict, assembled_json: str | None) -> tuple[float, str | None]:
    """Observer-Logik: berechnet Quality-Score und welcher Slave wiederholt werden soll.

    Returns (score 0.0–1.0, retry_signal | None).
    """
    # Bridge nicht erreichbar → Instrument-Problem
    if not report.get("ok", True) and report.get("track_count") is None:
        return 0.0, "instrument_retry"

    warnings = report.get("warnings", [])
    track_count = report.get("track_count")

    score = 1.0

    # Keine Tracks erkannt → Instrument-Retry
    if track_count == 0:
        return 0.0, "instrument_retry"

    # Jede Warning kostet 0.15 Punkte
    score -= len(warnings) * 0.15

    # Noten-Dichte aus assembled_json prüfen
    retry_for: str | None = None
    if assembled_json:
        try:
            proj = json.loads(assembled_json)
            for t in proj.get("tracks", []):
                notes = t.get("clip", {}).get("notes", [])
                length = float(t.get("clip", {}).get("length_beats", 16) or 16)
                density = len(notes) / max(length, 1)
                if density < 0.25:  # weniger als 1 Note pro 4 Beats
                    score -= 0.20
                    retry_for = "note_retry"
        except Exception:
            pass

    score = max(0.0, min(1.0, score))

    # Wenn Score unter Schwelle: passendes Signal bestimmen
    if score < 0.75 and not retry_for:
        warning_text = " ".join(warnings).lower()
        if "track" in warning_text or "instrument" in warning_text:
            retry_for = "instrument_retry"
        else:
            retry_for = "note_retry"

    return score, (retry_for if score < 0.75 else None)


def verify_node(state: AgentState) -> dict:
    """Observer-Node: ruft verify_song auf, bewertet Qualität, setzt retry_signal."""
    try:
        from src.agent.tools.song_tools import verify_song
        log.info("verify: verify_song aufrufen")
        result = verify_song.invoke({"play_seconds": 3, "slot": 0, "expected_tracks": 1})

        # verify_song gibt dict zurück
        report = result if isinstance(result, dict) else {"raw": str(result)}

        warnings = report.get("warnings", [])
        thresholds = state.get("quality_thresholds") or {"overall": 0.75}
        budget = dict(state.get("retry_budget") or {})

        score, signal = _compute_quality(report, state.get("assembled_json"))

        log.info("verify: score=%.2f, warnings=%d, signal=%s", score, len(warnings), signal)

        # Budget prüfen — kein Retry wenn aufgebraucht
        if signal:
            slave_key = signal.replace("_retry", "")
            remaining = budget.get(slave_key, 0)
            if remaining <= 0:
                log.info("verify: Budget für %s erschöpft → kein Retry", slave_key)
                signal = None
            else:
                budget[slave_key] = remaining - 1
                log.info("verify: Retry %s, Budget jetzt %d", slave_key, budget[slave_key])

        phase = "done" if not signal else "verifying"

        update: dict = {
            "quality_report":     report,
            "generation_phase":   phase,
            "phase_quality_score": score,
            "retry_budget":       budget,
            "retry_signal":       signal,
        }

        # Bei Retry: alten assembled_json + slave_results zurücksetzen
        if signal:
            update["assembled_json"] = None
            update["build_result"]   = None
            update["slave_results"]  = [{"__reset__": True}]

        return update

    except Exception as exc:
        log.error("verify: Fehler: %s", exc)
        return {
            "quality_report":     {"error": str(exc)},
            "generation_phase":   "error",
            "phase_quality_score": 0.0,
            "retry_signal":       None,
        }


def reply_node(state: AgentState) -> dict:
    """Formuliert die finale Antwort an den User basierend auf dem State."""
    phase = state.get("generation_phase", "idle")
    report = state.get("quality_report") or {}
    plan = state.get("slave_plan") or {}
    assembled = state.get("assembled_json")

    if phase == "done":
        instrument = ""
        notes_count = 0
        if assembled:
            try:
                proj = json.loads(assembled)
                t = proj.get("tracks", [{}])[0]
                instrument = t.get("instrument", "")
                notes_count = len(t.get("clip", {}).get("notes", []))
            except Exception:
                pass
        msg = (
            f"Rock-Riff wurde in Bitwig angelegt: {instrument}, "
            f"{int(plan.get('bpm', 120))} BPM, {int(plan.get('beat_count', 16))} Beats, "
            f"{notes_count} Noten (mit Wiederholung)."
        )
    elif phase == "error":
        msg = "Fehler beim Erstellen des Tracks. Bitte Verbindung und Prompt prüfen."
    else:
        warnings = report.get("warnings", [])
        msg = f"Track erstellt mit {len(warnings)} Warnung(en): {'; '.join(warnings)}" if warnings else "Track erstellt."

    return {"messages": [AIMessage(content=msg)]}


# ── Routing ───────────────────────────────────────────────────────────────────

def fan_out_to_slaves(state: AgentState) -> list[Send]:
    """Fan-out: Instrument + Harmonie parallel starten."""
    return [
        Send("instrument_slave", state),
        Send("harmony_slave", state),
    ]


def route_after_assemble(state: AgentState) -> str:
    """Nach assemble: execute_build wenn JSON da, sonst Error."""
    if state.get("assembled_json"):
        return "execute_build"
    # Prüfe ob Retry noch möglich
    retry_counts = state.get("slave_retry_counts") or {}
    if any(v >= _MAX_SLAVE_RETRIES for v in retry_counts.values()):
        return "reply"  # Maximale Retries erreicht → Fehler-Reply
    return "reply"


def route_after_verify(state: AgentState) -> str:
    """Nach verify: bei retry_signal zurück zu plan (neu fan-out), sonst reply."""
    signal = state.get("retry_signal")
    phase  = state.get("generation_phase", "idle")

    if phase == "error":
        return "reply"

    if signal in ("instrument_retry", "harmony_retry", "note_retry"):
        log.info("route_after_verify: %s → zurück zu plan", signal)
        return "plan"

    return "reply"


# ── Graph-Aufbau ──────────────────────────────────────────────────────────────

def build_master_graph():
    graph = StateGraph(AgentState)

    graph.add_node("plan", plan_node)
    graph.add_node("instrument_slave", run_instrument_slave)
    graph.add_node("harmony_slave", run_harmony_slave)
    graph.add_node("note_slave", run_note_slave)
    graph.add_node("assemble", assemble_node)
    graph.add_node("execute_build", execute_build_node)
    graph.add_node("verify", verify_node)
    graph.add_node("reply", reply_node)

    # Einstieg
    graph.set_entry_point("plan")

    # Fan-out: plan → parallele Slaves via Send
    graph.add_conditional_edges("plan", fan_out_to_slaves, ["instrument_slave", "harmony_slave"])

    # Fan-in Stufe 1: Instrument + Harmonie -> Note-Slave
    graph.add_edge("instrument_slave", "note_slave")
    graph.add_edge("harmony_slave", "note_slave")

    # Fan-in Stufe 2: Note-Slave -> Assemble
    graph.add_edge("note_slave", "assemble")

    # assemble → execute_build oder reply (Fehler)
    graph.add_conditional_edges("assemble", route_after_assemble, {
        "execute_build": "execute_build",
        "reply": "reply",
    })

    graph.add_edge("execute_build", "verify")

    # verify → reply (done/error) ODER zurück zu plan (retry_signal gesetzt)
    graph.add_conditional_edges("verify", route_after_verify, {
        "plan":  "plan",
        "reply": "reply",
    })

    graph.add_edge("reply", END)

    return graph.compile()


_MASTER_GRAPH = None


def get_master_graph():
    global _MASTER_GRAPH
    if _MASTER_GRAPH is None:
        _MASTER_GRAPH = build_master_graph()
    return _MASTER_GRAPH


def run_master(user_text: str, history: list | None = None, ui_song_config: dict | None = None) -> str:
    """Einstiegspunkt für den Master-Graph."""
    from src.agent.core import _default_state
    state = _default_state()
    state["messages"] = list(history or []) + [HumanMessage(content=user_text)]
    state["slave_results"] = []
    state["slave_retry_counts"] = {}
    state["slave_plan"] = None
    state["assembled_json"] = None
    state["build_result"] = None
    state["ui_song_config"] = dict(ui_song_config) if ui_song_config else None

    graph = get_master_graph()
    result = graph.invoke(state)
    last = result.get("messages", [])
    return last[-1].content if last else "(keine Antwort)"
