"""
Track-State und OSC-Verbindung via BitwigStepPlugin (Port 8002) und AgentBridge (8001).
"""
from __future__ import annotations
import os
import time

from dotenv import load_dotenv
load_dotenv()

OSC_HOST            = os.getenv("BITWIG_HOST",        "127.0.0.1")
OSC_PORT            = int(os.getenv("BITWIG_PORT",    "8001"))
OSC_REPLY_PORT      = int(os.getenv("BITWIG_REPLY_PORT", "9001"))
OSC_STEP_PORT       = int(os.getenv("BITWIG_STEP_PORT",  "8002"))
OSC_STEP_REPLY_PORT = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002"))


def _osc_client():
    from pythonosc import udp_client
    return udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)


def _bound_osc_client(timeout: float | None = None):
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT, allow_broadcast=False)
    sock = client._sock
    if timeout is not None:
        sock.settimeout(timeout)
    try:
        sock.bind(("", OSC_REPLY_PORT))
    except OSError:
        pass
    return client


def _get_note_counts() -> dict[str, int]:
    import socket
    import struct
    from pythonosc import udp_client as _udp
    client = _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT, allow_broadcast=False)
    sock   = client._sock
    sock.settimeout(2.0)
    try:
        sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError:
        pass
    try:
        client.send_message("/clip/note/count/all", 1)
        data, _ = sock.recvfrom(4096)
        raw = data.decode("latin-1")
        idx_s = raw.find(",is")
        if idx_s < 0:
            return {}
        count_start = idx_s + 4
        if count_start + 4 > len(data):
            return {}
        total      = struct.unpack(">i", data[count_start:count_start + 4])[0]
        str_start  = count_start + 4
        null_pos   = data.find(b"\x00", str_start)
        if null_pos <= str_start:
            return {"__total__": total}
        detail_str = data[str_start:null_pos].decode("utf-8", errors="ignore")
        result: dict[str, int] = {}
        for part in detail_str.split(";"):
            if "=" in part:
                name, cnt = part.rsplit("=", 1)
                try:
                    result[name] = int(cnt)
                except ValueError:
                    pass
        return result
    except (socket.timeout, OSError):
        return {}
    finally:
        try: sock.close()
        except (OSError, ValueError, socket.timeout):
            pass


def _reset_note_counts() -> None:
    from pythonosc import udp_client as _udp
    client = _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT)
    try:
        client.send_message("/clip/note/count/reset", 1)
    except OSError as e:
        log_debug = os.environ.get("DEBUG_OSC")
        if log_debug:
            import logging
            logging.debug("OSC reset failed: %s", e)
    finally:
        try:
            client._sock.close()
        except OSError:
            pass


def _get_current_track_count() -> int:
    import socket
    import struct
    client = _bound_osc_client(timeout=1.5)
    try:
        client.send_message("/agent/track/count", 1)
        data, _ = client._sock.recvfrom(512)
        raw     = data.decode("latin-1")
        tag_idx = raw.find(",i")
        if tag_idx >= 0:
            padded = (tag_idx + 4) & ~3
            if padded + 4 <= len(data):
                count = struct.unpack(">i", data[padded:padded + 4])[0]
                if 0 <= count <= 64:
                    return count
    except (socket.timeout, OSError):
        pass
    finally:
        try: client._sock.close()
        except (OSError, ValueError, socket.timeout):
            pass
    return 0


def _get_track_names() -> list[str]:
    import socket
    client = _bound_osc_client(timeout=2.0)
    try:
        client.send_message("/agent/track/count", 1)
        data, _ = client._sock.recvfrom(4096)
        raw      = data.decode("latin-1")
        idx_s    = raw.find(",is")
        if idx_s >= 0:
            str_start = idx_s + 8
            null_pos  = data.find(b"\x00", str_start)
            if null_pos > str_start:
                names_str = data[str_start:null_pos].decode("utf-8", errors="ignore")
                return [n.strip() for n in names_str.split(",") if n.strip()]
    except (socket.timeout, OSError):
        pass
    finally:
        try: client._sock.close()
        except (OSError, ValueError, socket.timeout):
            pass
    return []


def _clear_all_tracks(timeout: float = 5.0) -> int:
    """Löscht alle Tracks und wartet bis Bitwig den State synchronisiert hat.

    Bitwig verarbeitet `/agent/tracks/clear` asynchron — der Reply kommt sofort,
    aber der Project-State wird erst über mehrere Event-Loops aktualisiert.
    Wir pollen bis `track_count == 0` oder Timeout, damit Folge-Tests auf einem
    deterministisch leeren Projekt starten.
    """
    import socket
    import struct
    client   = _bound_osc_client(timeout=timeout)
    reported = 0
    try:
        client.send_message("/agent/tracks/clear", 1)
        data, _ = client._sock.recvfrom(512)
        raw     = data.decode("latin-1")
        tag_idx = raw.find(",i")
        if tag_idx >= 0:
            padded = (tag_idx + 4) & ~3
            if padded + 4 <= len(data):
                reported = struct.unpack(">i", data[padded:padded + 4])[0]
    except (socket.timeout, OSError):
        pass
    finally:
        try:
            client._sock.close()
        except OSError:
            pass

    # Polling: auf tatsächlich leeren Projekt-State warten (max. 3 s)
    deadline  = time.monotonic() + 3.0
    remaining = _get_current_track_count()
    while remaining > 0 and time.monotonic() < deadline:
        time.sleep(0.15)
        remaining = _get_current_track_count()

    # Fallback: per Einzel-Delete nachräumen wenn Bulk-Clear nicht alles erwischt hat
    if remaining > 0:
        from pythonosc import udp_client as _udp
        fb = _udp.SimpleUDPClient(OSC_HOST, OSC_PORT)
        for _ in range(remaining):
            fb.send_message("/track/1/select", 1)
            time.sleep(0.15)
            fb.send_message("/track/delete/last", 1)
            time.sleep(0.25)
        # nach Einzel-Delete erneut warten bis State leer ist
        deadline = time.monotonic() + 2.0
        while _get_current_track_count() > 0 and time.monotonic() < deadline:
            time.sleep(0.15)
        _reset_note_counts()
        return reported + remaining
    return reported


def _check_bridge(timeout: float = 1.5) -> bool:
    import socket
    from src.agent.osc.circuit_breaker import get_circuit
    circuit = get_circuit()
    client  = _bound_osc_client(timeout=timeout)
    sock    = client._sock
    try:
        client.send_message("/ping", 1)
        sock.recvfrom(64)
        circuit._on_success()
        return True
    except (socket.timeout, OSError):
        circuit._on_failure()
        return False
    finally:
        try: sock.close()
        except (OSError, ValueError, socket.timeout):
            pass
