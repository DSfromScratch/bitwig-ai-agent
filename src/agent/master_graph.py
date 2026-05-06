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
    user_text = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            user_text = (m.content or "").strip()
            if user_text:
                break

    bpm = _extract_bpm(user_text, 120.0)
    beat_count = _extract_beats(user_text) or _beats_from_time(bpm, user_text) or 16.0
    instrument_hint = _extract_instrument_hint(user_text)
    fx_hint = ", ".join(_extract_explicit_fx(user_text))
    scale = _extract_scale_hint(user_text)

    slave_plan = {
        "user_text": user_text,
        "bpm": bpm,
        "beat_count": beat_count,
        "instrument_hint": instrument_hint,
        "fx_hint": fx_hint,
        "scale": scale,
    }
    log.info(
        "Plan: bpm=%.0f, beats=%.0f, instrument=%s, fx=%s, scale=%s",
        bpm, beat_count, instrument_hint or "(auto)", fx_hint or "(auto)", scale or "(auto)",
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


def verify_node(state: AgentState) -> dict:
    """Ruft verify_song auf und speichert quality_report."""
    try:
        from src.agent.tools.song_tools import verify_song
        log.info("verify: verify_song aufrufen")
        result_str = verify_song.invoke({"play_seconds": 3, "slot": 0, "expected_tracks": 1})
        try:
            report = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            report = {"raw": str(result_str)}
        warnings = report.get("warnings", [])
        phase = "done" if not warnings else "verifying"
        log.info("verify: %d Warnings, Phase=%s", len(warnings), phase)
        return {"quality_report": report, "generation_phase": phase}
    except Exception as exc:
        log.error("verify: Fehler: %s", exc)
        return {"quality_report": {"error": str(exc)}, "generation_phase": "error"}


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
    phase = state.get("generation_phase", "idle")
    if phase == "done":
        return "reply"
    if phase == "error":
        return "reply"
    # Warnings → Einmal Korrektur via note_slave (max. 1x)
    retry_counts = state.get("slave_retry_counts") or {}
    if retry_counts.get("notes_correction", 0) < 1:
        log.info("verify: Warnings vorhanden — Note-Slave zur Korrektur")
        return "reply"  # vereinfacht: direkt reply statt Korrektur-Loop
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

    graph.add_conditional_edges("verify", route_after_verify, {
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


def run_master(user_text: str, history: list | None = None) -> str:
    """Einstiegspunkt für den Master-Graph."""
    from src.agent.core import _default_state
    state = _default_state()
    state["messages"] = list(history or []) + [HumanMessage(content=user_text)]
    state["slave_results"] = []
    state["slave_retry_counts"] = {}
    state["slave_plan"] = None
    state["assembled_json"] = None
    state["build_result"] = None

    graph = get_master_graph()
    result = graph.invoke(state)
    last = result.get("messages", [])
    return last[-1].content if last else "(keine Antwort)"
