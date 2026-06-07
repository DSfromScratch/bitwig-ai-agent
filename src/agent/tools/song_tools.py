"""
Song-Erstellungs-Tools für den LangGraph-Agenten.

OSC-Kommunikation mit der BitwigAgentBridge — Helper-Funktionen
für Tests + zwei produktive @tool-Funktionen.
"""

from __future__ import annotations
import os
import time
from langchain_core.tools import tool


from dotenv import load_dotenv
load_dotenv()

OSC_HOST = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_PORT = int(os.getenv("BITWIG_PORT", "8001"))
OSC_REPLY_PORT = int(os.getenv("BITWIG_REPLY_PORT", "9001"))

# BitwigStepPlugin — Note-Counter + Track-Management
OSC_STEP_PORT       = int(os.getenv("BITWIG_STEP_PORT",       "8002"))
OSC_STEP_REPLY_PORT = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002"))

# ── Re-exports für Backward-Kompatibilität (Bridge-Pattern — Phase 8 entfernen) ──
from src.agent.osc.device_uuid import (  # noqa: F401
    _DEVICE_UUID_CACHE, _SYNCED_FROM_EXTENSION,
    _build_osc_message, _sync_device_uuids_from_extension,
    _get_device_uuid_map, _lookup_device_uuid, invalidate_device_uuid_cache,
)
from src.agent.osc.track_state import (  # noqa: F401
    OSC_STEP_PORT, OSC_STEP_REPLY_PORT,
    _osc_client, _bound_osc_client,
    _get_note_counts, _reset_note_counts, _clear_all_tracks,
    _get_track_names, _get_current_track_count, _check_bridge,
)


@tool
def check_bitwig_connection() -> dict:
    """Prüft ob Bitwig Studio erreichbar ist (BitwigStepPlugin Port 8002).

    Muss vor allen Song-Operationen aufgerufen werden.
    Returns: {"connected": bool, "message": str}
    """
    # Primär: BitwigStepPlugin Port 8002 (läuft auf Mac + Linux)
    import socket
    from pythonosc import udp_client as _udp
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try: sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError: pass
    sock.settimeout(2.0)
    try:
        sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError:
        pass
    try:
        _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT).send_message("/ping", 1)
        sock.recvfrom(64)
        return {"connected": True, "message": "Bitwig erreichbar ✓ (BitwigStepPlugin)"}
    except (socket.timeout, OSError):
        pass
    finally:
        try: sock.close()
        except (OSError, ValueError, socket.timeout):
            pass

    # Fallback: BitwigAgentBridge Port 8001
    ok = _check_bridge()
    return {
        "connected": ok,
        "message": (
            "Bitwig erreichbar ✓ (BitwigAgentBridge)" if ok else
            "Bitwig nicht erreichbar — Bitwig starten + BitwigStepPlugin aktivieren (Port 8002)"
        ),
    }


@tool
def get_bitwig_track_state() -> str:
    """Liest den aktuellen Bitwig Track-Zustand via OSC aus.

    Gibt Anzahl vorhandener Tracks, deren Namen und den nächsten freien
    track_index zurück. Vor execute_result aufrufen wenn unklar ob Tracks
    bereits vorhanden sind.
    """
    import struct

    result_holder = {}
    # Direkt BitwigStepPlugin Port 8002 verwenden (funktioniert auf Mac + Linux)
    import socket as _socket
    from pythonosc import udp_client as _udp2
    step_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    step_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    if hasattr(_socket, "SO_REUSEPORT"):
        try: step_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
        except OSError: pass
    step_sock.settimeout(2.0)
    try: step_sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError: pass

    class _StepClient:
        def __init__(self): self._sock = step_sock
        def send_message(self, addr, val):
            _udp2.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT).send_message(addr, val)

    client = _StepClient()
    try:
        client.send_message("/agent/track/count", 1)
        data, _ = client._sock.recvfrom(4096)
        raw = data.decode("latin-1")
        idx_s = raw.find(",is")
        if idx_s >= 0:
            count_bytes = data[idx_s + 4 : idx_s + 8]
            if len(count_bytes) == 4:
                result_holder["count"] = struct.unpack(">i", count_bytes)[0]
            str_start = idx_s + 8
            null_pos  = data.find(b"\x00", str_start)
            if null_pos > str_start:
                result_holder["names"] = data[str_start:null_pos].decode("utf-8", errors="ignore")
        elif raw.find(",i") >= 0:
            idx = raw.find(",i")
            count_bytes = data[idx + 4 : idx + 8]
            if len(count_bytes) == 4:
                result_holder["count"] = struct.unpack(">i", count_bytes)[0]
    except OSError:
        pass
    finally:
        try: step_sock.close()
        except (OSError, ValueError, socket.timeout):
            pass

    if "count" in result_holder:
        count      = result_holder["count"]
        names_raw  = result_holder.get("names", "")
        track_list = [n.strip() for n in names_raw.split(",") if n.strip()] if names_raw else []
        next_idx   = count + 1

        if count == 0:
            return "Bitwig Track-Zustand: Leeres Projekt — start_track_index=1"

        lines = ["Bitwig Track-Zustand:"]
        for idx_t, name in enumerate(track_list, start=1):
            lines.append(f"  Track {idx_t}: {name}")
        if len(track_list) < count:
            lines.append(f"  ... ({count} Tracks gesamt)")
        lines.append(f"Vorhandene Tracks: {count}")
        lines.append(
            f"→ Diese Tracks bereits belegt — nur Noten schreiben (write_drum_pattern/write_notes) "
            f"mit track_index 1..{count}, KEIN add_track, KEIN load_instrument."
        )
        lines.append(f"→ Neue Tracks (falls nötig) ab track_index={next_idx}.")
        return "\n".join(lines)

    return "Track-Zustand unbekannt — Annahme: leeres Projekt, start_track_index=1"
