"""
OSC-Helfer für /agent/project/scan + /agent/track/params.
Kommuniziert mit BitwigStepPlugin auf Port 8002, empfängt auf 9002.
"""
from __future__ import annotations
import json
import re
import socket
import struct
import time

from src.agent.osc.track_state import OSC_HOST, OSC_STEP_PORT, OSC_STEP_REPLY_PORT


def query_osc(send_address: str, reply_contains: str,
              send_args: tuple = (), timeout: float = 4.0) -> str | None:
    """Bind zuerst → sende OSC → warte auf Antwort. Löst Race Condition."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    sock.settimeout(timeout)
    try:
        sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError:
        pass

    _send(send_address, *send_args) if send_args else _send(send_address, 1)

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(65536)
            except socket.timeout:
                break
            raw = data.decode("latin-1")
            if reply_contains not in raw:
                continue
            addr_end = data.find(b"\x00")
            if addr_end < 0:
                continue
            tt_start = (addr_end + 4) & ~3
            if tt_start >= len(data) or data[tt_start:tt_start+1] != b",":
                continue
            tt_end = data.find(b"\x00", tt_start)
            if tt_end < 0:
                continue
            type_tag = data[tt_start+1:tt_end].decode("ascii", errors="ignore")
            data_start = (tt_end + 4) & ~3
            pos = data_start
            for c in type_tag:
                if c == "i":
                    pos += 4
                elif c == "f":
                    pos += 4
                elif c == "s":
                    s_end = data.find(b"\x00", pos)
                    if s_end < 0:
                        s_end = len(data)
                    result = data[pos:s_end].decode("utf-8", errors="replace")
                    sock.close()
                    return result
    except socket.timeout:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return None


def _osc_str_reply(address: str, timeout: float = 3.0,
                   reply_address: str | None = None) -> str | None:
    """Wartet auf OSC-Nachricht, gibt ersten String-Arg zurück.

    reply_address: zu erwartende Antwort-Adresse (default: address + "/response")
    """
    if reply_address is None:
        reply_address = address if address.endswith("/response") else address + "/response"
    address = reply_address
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    sock.settimeout(timeout)
    try:
        sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError:
        pass

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(65536)
            except socket.timeout:
                break

            # OSC-Adresse dekodieren
            raw = data.decode("latin-1")
            if address not in raw:
                continue  # Antwort für andere Adresse — weiterwarten

            # Ersten String-Argument aus OSC-Payload extrahieren
            # Format: <address>\0<pad> <typetag>\0<pad> <data>
            addr_end = data.find(b"\x00")
            if addr_end < 0:
                continue
            # Skip to type-tag (nach 4-Byte-Padding)
            tt_start = (addr_end + 4) & ~3
            if tt_start >= len(data) or data[tt_start:tt_start + 1] != b",":
                continue
            tt_end = data.find(b"\x00", tt_start)
            if tt_end < 0:
                continue
            type_tag = data[tt_start + 1:tt_end].decode("ascii", errors="ignore")

            # Daten-Block (nach 4-Byte-Padding)
            data_start = (tt_end + 4) & ~3

            # Alle Argumente der Reihe nach lesen
            pos = data_start
            args: list = []
            for c in type_tag:
                if c == "i":
                    if pos + 4 > len(data):
                        break
                    args.append(struct.unpack(">i", data[pos:pos + 4])[0])
                    pos += 4
                elif c == "f":
                    if pos + 4 > len(data):
                        break
                    args.append(struct.unpack(">f", data[pos:pos + 4])[0])
                    pos += 4
                elif c == "s":
                    s_end = data.find(b"\x00", pos)
                    if s_end < 0:
                        s_end = len(data)
                    args.append(data[pos:s_end].decode("utf-8", errors="replace"))
                    pos = (s_end + 4) & ~3

            # Ersten String-Arg zurückgeben
            for a in args:
                if isinstance(a, str) and a:
                    return a
            return None
    except socket.timeout:
        pass
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return None


def _send(address: str, *args):
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT)
    try:
        client.send_message(address, list(args) if args else 1)
    finally:
        try:
            client._sock.close()
        except Exception:
            pass


def scan_project(timeout: float = 5.0) -> dict:
    """Ruft /agent/project/scan auf, gibt geparsten Dict zurück.

    Returns:
        {"tracks": [{"idx": 1, "name": "Kick", "devices": ["Poly Grid"]}, ...],
         "tempo": 130.0, "total": 12}
    """
    raw = query_osc("/agent/project/scan", "/agent/project/scan/response", timeout=timeout)
    if not raw:
        return {"tracks": [], "tempo": 0.0, "total": 0}
    try:
        # Locale-Fix: deutsches Komma als Dezimaltrenner (Java String.format ohne Locale.US)
        return json.loads(raw.replace(",\"", ',"').replace("\"tempo\":", '"tempo":')
                          if False else raw)
    except json.JSONDecodeError:
        # Fallback: tempo-Komma reparieren (z.B. "tempo\":130,0" → "tempo\":130.0")
        import re
        fixed = re.sub(r'("tempo"\s*:\s*)(\d+),(\d+)', r'\g<1>\2.\3', raw)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return {"tracks": [], "tempo": 0.0, "total": 0, "_raw": raw}


def query_track_params_all(track_index: int, timeout: float = 20.0) -> dict:
    """Ruft /agent/track/params/all auf — liest ALLE Remote-Control-Seiten.

    Returns:
        {"track": 1, "device": "Poly Grid", "page_count": 5, "total_pages": 5,
         "pages": [{"page": 0, "name": "Oscillators", "params": [...]}]}
    """
    raw = query_osc("/agent/track/params/all", "/agent/track/params/all/response",
                   send_args=(float(track_index),), timeout=timeout)
    if not raw:
        return {"track": track_index, "device": "", "pages": [], "total_pages": 0}
    try:
        fixed = re.sub(r'("value"\s*:\s*)(\d+),(\d+)', r'\g<1>\2.\3', raw)
        return json.loads(fixed)
    except json.JSONDecodeError:
        return {"track": track_index, "device": "", "pages": [], "total_pages": 0, "_raw": raw}


def query_track_clip_notes(track_index: int, scene_idx: int = 0,
                           timeout: float = 5.0) -> dict:
    """Liest MIDI-Noten aus einem Launcher-Clip eines Tracks.

    Args:
        track_index: Track-Index (1-basiert)
        scene_idx:   Szenen-Slot (1-basiert). 0 = erster Slot mit Inhalt (default)

    Returns:
        {"track": 1, "loop_beats": 8.0, "count": 12, "scene_slot": 1,
         "notes": [{"step": 0, "pitch": 60}, ...]}
    """
    args = (float(track_index), float(scene_idx)) if scene_idx > 0 else (float(track_index),)
    raw = query_osc("/agent/track/clip/notes", "/agent/track/clip/notes/response",
                   send_args=args, timeout=timeout)
    if not raw:
        return {"track": track_index, "notes": [], "count": 0, "loop_beats": 0}
    try:
        fixed = re.sub(r'(\d),(\d)', r'\1.\2', raw)
        return json.loads(fixed)
    except json.JSONDecodeError:
        return {"track": track_index, "notes": [], "count": 0, "_raw": raw[:200]}


def open_track_device(track_index: int, timeout: float = 3.0) -> str:
    """Öffnet das Device-Fenster des ersten Geräts auf einem Track.
    Returns device name oder "" bei Fehler.
    """
    return query_osc("/agent/track/device/open", "/agent/track/device/open/response",
                    send_args=(float(track_index),), timeout=timeout) or ""


def query_track_params(track_index: int, timeout: float = 3.0) -> dict:
    """Ruft /agent/track/params auf, gibt geparsten Dict zurück.

    Returns:
        {"track": 1, "device": "Poly Grid",
         "params": [{"name": "Filter Cutoff", "value": 0.4321}, ...]}
    """
    raw = query_osc("/agent/track/params", "/agent/track/params/response",
                   send_args=(float(track_index),), timeout=timeout)
    if not raw:
        return {"track": track_index, "device": "", "params": []}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"track": track_index, "device": "", "params": [], "_raw": raw}


def new_project(timeout: float = 3.0) -> str:
    """Erstellt ein neues leeres Bitwig-Projekt. Gibt den Namen zurück."""
    return query_osc("/agent/project/new", "/agent/project/new/response",
                    timeout=timeout) or "Neues Projekt"


def query_cursor_track(timeout: float = 3.0) -> dict:
    """Gibt Name + Devices des aktuell in Bitwig ausgewählten Tracks zurück.

    Returns:
        {"name": "Bass", "devices": ["Operator"], "is_group": False}
    """
    raw = query_osc("/agent/cursor/track/info", "/agent/cursor/track/info/response",
                    timeout=timeout)
    if not raw:
        return {"name": "", "devices": [], "is_group": False}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"name": "", "devices": [], "is_group": False, "_raw": raw}


def query_arranger_clip_notes(timeout: float = 4.0) -> dict:
    """Liest MIDI-Noten aus dem aktuell ausgewählten Arranger-Clip.

    Voraussetzung: Playhead auf einem MIDI-Clip des ausgewählten Tracks.

    Returns:
        {"loop_beats": 8.0, "notes": [{"step": 0, "pitch": 60}, ...], "count": 12}
    """
    raw = query_osc("/agent/cursor/clip/notes", "/agent/cursor/clip/notes/response",
                    timeout=timeout)
    if not raw:
        return {"loop_beats": 0.0, "notes": [], "count": 0}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"loop_beats": 0.0, "notes": [], "count": 0, "_raw": raw}


def get_project_name(timeout: float = 2.0) -> str:
    """Gibt den Namen des aktuell geöffneten Bitwig-Projekts zurück."""
    return query_osc("/agent/project/name", "/agent/project/name/response",
                    timeout=timeout) or ""


def save_project(timeout: float = 3.0) -> str:
    """Speichert das aktuell geöffnete Bitwig-Projekt. Gibt Projektname zurück."""
    return query_osc("/agent/project/save", "/agent/project/save/response",
                    timeout=timeout) or ""


def launch_clip(track_index: int, slot: int = 0, timeout: float = 2.0) -> bool:
    """Startet einen Launcher-Clip auf einem Track. Gibt True bei Erfolg zurück."""
    reply = query_osc("/agent/track/clip/launch",
                     "/agent/track/clip/launch/response",
                     send_args=(float(track_index), float(slot)),
                     timeout=timeout)
    return bool(reply and reply.startswith("launched"))


def query_cue_markers(timeout: float = 3.0) -> list[dict]:
    """Liest Arranger Cue Markers (Sektionsmarker mit Beat-Position).

    Returns:
        [{"name": "Intro", "beat": 0.0, "bar": 1.0}, ...]
    """
    raw = query_osc("/agent/project/cue-markers", "/agent/project/cue-markers/response",
                   timeout=timeout)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data.get("markers", [])
    except json.JSONDecodeError:
        return []


def query_project_snapshot(project_name: str, timeout: float = 8.0):
    """Vollständiger Projekt-Scan in einem OSC-Roundtrip.

    Ruft /agent/project/full-snapshot auf und gibt ein BitwigProjectSnapshot zurück.
    Beinhaltet: alle Tracks + Geräte, Szenen-Namen, Gruppen-Hierarchie, Tempo.

    Returns:
        BitwigProjectSnapshot oder raises RuntimeError wenn Bitwig nicht erreichbar.
    """
    from src.agent.models.project_snapshot import BitwigProjectSnapshot
    raw = query_osc("/agent/project/full-snapshot",
                   "/agent/project/full-snapshot/response", timeout=timeout)
    if not raw:
        raise RuntimeError("Bitwig nicht erreichbar (/agent/project/full-snapshot)")
    return BitwigProjectSnapshot.from_raw(project_name, raw)
