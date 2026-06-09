"""
Song-Erstellungs-Tools für den LangGraph-Agenten.

OSC-Kommunikation mit der BitwigAgentBridge — Helper-Funktionen
für Tests + zwei produktive @tool-Funktionen.
"""

from __future__ import annotations
import os
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
    from src.agent.osc.client import configure_dgram_socket
    sock = configure_dgram_socket(
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM),
        timeout=2.0, reuse_port=True,
    )
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
    from src.agent.osc.client import configure_dgram_socket
    step_sock = configure_dgram_socket(
        _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM),
        timeout=2.0, reuse_port=True,
    )
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
        except (OSError, ValueError):
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


@tool
def get_bitwig_state() -> str:
    """Prüft Bitwig-Verbindung und gibt den aktuellen Track-Zustand zurück.

    Kombiniert Verbindungscheck und Track-Snapshot in einem Aufruf.
    Vor execute_setup oder write_pattern_raw aufrufen um den Ist-Zustand zu kennen.
    Returns: Verbindungsstatus + Anzahl/Namen vorhandener Tracks.
    """
    conn = check_bitwig_connection.invoke({})
    if isinstance(conn, dict) and not conn.get("connected", True):
        return f"Bitwig nicht erreichbar. {conn.get('message', '')}"

    track_state = get_bitwig_track_state.invoke({})
    conn_msg = conn.get("message", "Bitwig erreichbar") if isinstance(conn, dict) else str(conn)
    return f"{conn_msg}\n{track_state}"
