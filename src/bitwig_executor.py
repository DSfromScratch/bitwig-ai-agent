"""
Bitwig Step-Executor — Agent-Adapter für bitwigbridge.

Verbindet bitwigbridge (OSC-Layer) mit Agent-spezifischen Komponenten:
  - EventBus für LangGraph-Events
  - Neo4j Drum-Pattern-Resolver
  - BitwigProjectState für Precondition-Checks
  - Device-UUID-Cache

Workflow:
  execute_setup() — Tracks, Instrumente, FX, Tempo
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
load_dotenv()

from bitwigbridge.executor import (
    execute_setup as _bb_execute_setup,
    execute_result as _bb_execute_result,
    _SETUP_TYPES,        # noqa: F401  re-export
    _exec_step_and_wait, # noqa: F401  re-export (für Tests + MCP-Server)
)
from bitwigbridge.connection import BitwigConnection  # noqa: E402
from src.agent.error_handler import log_error, ErrorDomain

# ── Agent-spezifische Interfaces ──────────────────────────────────────────────

def _get_event_emitter():
    """Gibt den Agent-EventBus zurück (optional)."""
    try:
        from src.agent.events import get_event_bus
        bus = get_event_bus()

        class _BusAdapter:
            def emit(self, event: str, data: dict) -> None:
                bus.emit(event, data)

        return _BusAdapter()
    except Exception:
        return None


def _get_drum_resolver():
    """Gibt den Neo4j Drum-Pattern-Resolver zurück (optional)."""
    try:
        from src.knowledge.repositories import DrumPatternRepository
        return DrumPatternRepository()
    except Exception:
        return None


def _get_device_resolver():
    """Gibt den UUID-Resolver zurück (optional)."""
    try:
        from src.agent.osc.device_uuid import _lookup_device_uuid

        class _UUIDAdapter:
            def lookup(self, name: str):
                return _lookup_device_uuid(name)

        return _UUIDAdapter()
    except Exception:
        return None


def _make_connection() -> BitwigConnection:
    """Erstellt BitwigConnection mit allen Agent-Callbacks."""
    return BitwigConnection(
        host              = os.getenv("BITWIG_HOST", "127.0.0.1"),
        step_port         = int(os.getenv("BITWIG_STEP_PORT", "8002")),
        step_reply_port   = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002")),
        event_emitter     = _get_event_emitter(),
        drum_resolver     = _get_drum_resolver(),
        device_resolver   = _get_device_resolver(),
    )


def _as_dict(result) -> dict:
    """Konvertiert Pydantic-Modelle zu dict; passiert plain dicts unverändert."""
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result


def _track_count_status() -> str:
    """Hängt 'Bitwig-Status: N Track(s)' an wenn Track-Count > 0."""
    try:
        from src.agent.osc.track_state import _get_current_track_count
        count = _get_current_track_count()
        if count > 0:
            return f"\nBitwig-Status: {count} Track(s)"
    except Exception as _e:
        log_error(ErrorDomain.OSC, _e, "bitwig_executor._track_count_status")
    return ""


def _check_connection(timeout: float = 1.5) -> bool:
    """Prüft ob Bitwig erreichbar ist (nutzt _check_bridge für Test-Kompatibilität)."""
    try:
        from src.agent.osc.track_state import _check_bridge
        if _check_bridge(timeout=timeout):
            return True
    except Exception:
        pass
    try:
        return _make_connection().is_connected()
    except Exception:
        return False


# ── Öffentliche API (Backward-kompatibel) ────────────────────────────────────

def execute_setup(result: dict) -> str:
    """Phase 1: Tracks, Instrumente, FX, Tempo anlegen. Keine Noten.

    Delegiert an bitwigbridge.executor.execute_setup mit Agent-Callbacks.
    """
    result = _as_dict(result)
    if not _check_connection():
        label = result.get("context_type", "execute_setup")
        return (f"[{label}] BitwigStepPlugin nicht erreichbar "
                "— Bitwig starten und Extension aktivieren")

    conn = _make_connection()

    # Drum-Profil nach erfolgreichem load_instrument setzen
    def _on_step_done(payload: dict) -> None:
        if payload.get("type") == "load_instrument":
            name = payload.get("args", {}).get("name", "")
            if name and any(k in name.lower() for k in
                            {"drum", "vd-", "vd_", "mt-power", "v0 ", "v1 ", "v8 ", "v9 "}):
                try:
                    from src.agent.tools.bitwig.suggest_tools import set_drum_profile
                    set_drum_profile(name)
                except Exception as _e:
                    log_error(ErrorDomain.TOOL, _e, "bitwig_executor.set_drum_profile")

    result_str = _bb_execute_setup(result, connection=conn, on_step_done=_on_step_done)
    result_str += _track_count_status()
    return result_str


def execute_result(result: dict) -> str:
    """Rückwärtskompatibel: Setup + Noten in einem Call."""
    result = _as_dict(result)
    if not _check_connection():
        return ("[execute_result] BitwigStepPlugin nicht erreichbar "
                "— Bitwig starten und Extension aktivieren")

    conn = _make_connection()

    result_str = _bb_execute_result(result, connection=conn)
    result_str += _track_count_status()
    return result_str


