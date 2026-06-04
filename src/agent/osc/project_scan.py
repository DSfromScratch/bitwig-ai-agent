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
    _send("/agent/project/scan", 1)
    raw = _osc_str_reply("/agent/project/scan/response", timeout=timeout)
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
    _send("/agent/track/params/all", float(track_index))
    raw = _osc_str_reply("/agent/track/params/all/response", timeout=timeout)
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
    if scene_idx > 0:
        _send("/agent/track/clip/notes", float(track_index), float(scene_idx))
    else:
        _send("/agent/track/clip/notes", float(track_index))
    raw = _osc_str_reply("/agent/track/clip/notes/response", timeout=timeout)
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
    _send("/agent/track/device/open", float(track_index))
    raw = _osc_str_reply("/agent/track/device/open/response", timeout=timeout)
    return raw or ""


def query_track_params(track_index: int, timeout: float = 3.0) -> dict:
    """Ruft /agent/track/params auf, gibt geparsten Dict zurück.

    Returns:
        {"track": 1, "device": "Poly Grid",
         "params": [{"name": "Filter Cutoff", "value": 0.4321}, ...]}
    """
    _send("/agent/track/params", float(track_index))
    raw = _osc_str_reply("/agent/track/params/response", timeout=timeout)
    if not raw:
        return {"track": track_index, "device": "", "params": []}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"track": track_index, "device": "", "params": [], "_raw": raw}


def new_project(timeout: float = 3.0) -> str:
    """Erstellt ein neues leeres Bitwig-Projekt. Gibt den Namen zurück."""
    _send("/agent/project/new", 1)
    return _osc_str_reply("/agent/project/new",
                          reply_address="/agent/project/new/response",
                          timeout=timeout) or "Neues Projekt"


def get_project_name(timeout: float = 2.0) -> str:
    """Gibt den Namen des aktuell geöffneten Bitwig-Projekts zurück."""
    _send("/agent/project/name", 1)
    return _osc_str_reply("/agent/project/name",
                          reply_address="/agent/project/name/response",
                          timeout=timeout) or ""


def save_project(timeout: float = 3.0) -> bool:
    """Speichert das aktuell geöffnete Bitwig-Projekt. Gibt True bei Erfolg zurück."""
    _send("/agent/project/save", 1)
    reply = _osc_str_reply("/agent/project/save",
                           reply_address="/agent/project/save/response",
                           timeout=timeout)
    return reply == "ok"


def query_cue_markers(timeout: float = 3.0) -> list[dict]:
    """Liest Arranger Cue Markers (Sektionsmarker mit Beat-Position).

    Returns:
        [{"name": "Intro", "beat": 0.0, "bar": 1.0}, ...]
    """
    _send("/agent/project/cue-markers", 1)
    raw = _osc_str_reply("/agent/project/cue-markers",
                         reply_address="/agent/project/cue-markers/response",
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
    _send("/agent/project/full-snapshot", 1)
    raw = _osc_str_reply(
        "/agent/project/full-snapshot",
        reply_address="/agent/project/full-snapshot/response",
        timeout=timeout,
    )
    if not raw:
        raise RuntimeError("Bitwig nicht erreichbar (/agent/project/full-snapshot)")
    return BitwigProjectSnapshot.from_raw(project_name, raw)
