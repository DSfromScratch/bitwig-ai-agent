"""
OSC-Helfer für /agent/project/scan + /agent/track/params.
Kommuniziert mit BitwigStepPlugin auf Port 8002, empfängt auf 9002.
"""
from __future__ import annotations
import json
import socket
import struct
import time

from src.agent.osc.track_state import OSC_HOST, OSC_STEP_PORT, OSC_STEP_REPLY_PORT


def _osc_str_reply(address: str, timeout: float = 3.0) -> str | None:
    """Wartet auf eine OSC-Nachricht mit gegebener Adresse, gibt den ersten String-Arg zurück."""
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
