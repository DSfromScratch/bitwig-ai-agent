"""
Event-Bus — Observer-Pattern für Song-Generierungs-Feedback.

Emittiert strukturierte Events während der Song-Erstellung.
Subscriber können unabhängig voneinander lauschen (Logger, Dashboard, State-Update).

Verwendung:
    from src.agent.events import get_event_bus, SongEvent

    bus = get_event_bus()
    bus.subscribe("track_done", lambda e: print(e["payload"]))

    # In song_tools.py:
    get_event_bus().emit({"type": "track_done", "payload": {"role": "kick", "notes": 32}})
"""
from __future__ import annotations

import time
import logging
from typing import Callable, Literal
from typing_extensions import TypedDict

log = logging.getLogger("bitwig-agent.events")

EventType = Literal[
    "section_start",    # Section-Generierung beginnt
    "track_done",       # Ein Track-Pattern fertig geschrieben
    "section_done",     # Komplette Section fertig
    "fill_done",        # Drum-Fill zwischen Sections fertig
    "quality_check",    # verify_song läuft
    "quality_result",   # verify_song Ergebnis
    "error",            # Fehler in der Pipeline
    "song_done",        # Gesamter Song fertig
    "reasoning",        # LLM <think>-Inhalt — enthält phase_hint für State-Steuerung
    "phase_change",     # generation_phase hat sich geändert
    "invalid_tool_output",  # LLM lieferte kaputten/abgeschnittenen Tool-Call
    # ── Result-Executor Events ────────────────────────────────────────────────
    "result_step_done", # Ein Step erfolgreich ausgeführt: {type, args, index}
    "result_step_error",# Step fehlgeschlagen: {type, args, index, error}
    "result_done",      # Alle Steps abgearbeitet: {context_type, target, done, errors}
]


class SongEvent(TypedDict):
    type:      str          # EventType-Wert
    payload:   dict         # Kontext-Daten (section_name, role, note_count, ...)
    timestamp: float        # time.time()


class EventBus:
    """
    Einfacher synchroner Event-Bus (Singleton-Instanz via get_event_bus()).

    Subscriber werden per Event-Typ registriert und beim emit() nacheinander aufgerufen.
    Fehler in Subscribern werden geloggt, unterbrechen aber nicht die Pipeline.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[SongEvent], None]]] = {}

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[SongEvent], None],
    ) -> None:
        """Registriert einen Callback für einen Event-Typ.

        Args:
            event_type: z.B. "track_done" oder "*" für alle Events
            callback:   Callable, das ein SongEvent-Dict erhält
        """
        self._subscribers.setdefault(event_type, []).append(callback)

    def unsubscribe(self, event_type: str, callback: Callable[[SongEvent], None]) -> None:
        callbacks = self._subscribers.get(event_type, [])
        if callback in callbacks:
            callbacks.remove(callback)

    def emit(self, event_type: str, payload: dict | None = None) -> None:
        """Sendet ein Event an alle registrierten Subscriber.

        Args:
            event_type: Event-Typ-String
            payload:    Kontext-Daten (optional, default: leeres dict)
        """
        event: SongEvent = {
            "type": event_type,
            "payload": payload or {},
            "timestamp": time.time(),
        }
        for callback in list(self._subscribers.get(event_type, [])):
            try:
                callback(event)
            except Exception as exc:
                log.warning("EventBus-Subscriber '%s' Fehler: %s", event_type, exc)
        # Wildcard-Subscriber
        for callback in list(self._subscribers.get("*", [])):
            try:
                callback(event)
            except Exception as exc:
                log.warning("EventBus-Wildcard-Subscriber Fehler: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Gibt die Session-weite EventBus-Instanz zurück (lazy init)."""
    global _bus
    if _bus is None:
        _bus = EventBus()
        _register_default_subscribers(_bus)
    return _bus


def reset_event_bus() -> None:
    """Setzt den Bus zurück — primär für Tests."""
    global _bus
    _bus = None


# ── Default-Subscriber ────────────────────────────────────────────────────────

def _register_default_subscribers(bus: EventBus) -> None:
    """Registriert Standard-Subscriber (Logger)."""
    import os
    import json

    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    event_log_path = os.path.join(log_dir, "generation_events.jsonl")

    def _log_to_file(event: SongEvent) -> None:
        try:
            with open(event_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Logging-Fehler nie an Pipeline weitergeben

    def _log_to_logger(event: SongEvent) -> None:
        etype = event["type"]
        payload = event["payload"]
        if etype == "track_done":
            log.info("✓ Track '%s' — %d Noten", payload.get("role", "?"), payload.get("notes", 0))
        elif etype == "section_done":
            log.info("✓ Section '%s' fertig", payload.get("section", "?"))
        elif etype == "section_start":
            log.info("→ Section '%s' wird generiert …", payload.get("section", "?"))
        elif etype == "quality_result":
            ok = payload.get("ok", False)
            log.info("verify_song: %s", "PASS" if ok else "FAIL")
        elif etype == "error":
            log.error("Pipeline-Fehler: %s", payload.get("message", "?"))
        elif etype == "song_done":
            log.info("✓ Song fertig — %d Tracks", payload.get("track_count", 0))

    bus.subscribe("*", _log_to_file)
    bus.subscribe("track_done", _log_to_logger)
    bus.subscribe("section_start", _log_to_logger)
    bus.subscribe("section_done", _log_to_logger)
    bus.subscribe("quality_result", _log_to_logger)
    bus.subscribe("error", _log_to_logger)
    bus.subscribe("song_done", _log_to_logger)
