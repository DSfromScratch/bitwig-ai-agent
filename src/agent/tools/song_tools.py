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

# ── Device-UUID Lookup (Extension → Neo4j → In-Memory Cache) ─────────────────

_DEVICE_UUID_CACHE: dict[str, str] | None = None
_SYNCED_FROM_EXTENSION = False  # True nach erstem erfolgreichen Extension-Sync pro Prozess


def _sync_device_uuids_from_extension(timeout: float = 3.0) -> bool:
    """Holt BUILTIN_UUIDS von BitwigStepPlugin via /devices/export, schreibt nach Neo4j.

    Gibt True zurück wenn Sync erfolgreich. Füllt _DEVICE_UUID_CACHE direkt.
    Verwendet einen eigenen Socket (kein SimpleUDPClient) um Port-Konflikte zu vermeiden.
    Filtert Pakete nach OSC-Adresse — verwirft veraltete /step/done Reste im Puffer.
    """
    global _DEVICE_UUID_CACHE
    import socket, json as _json
    from pythonosc import udp_client as _udp

    # Eigener Socket für Send+Receive
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError:
        sock.close()
        return False  # Port belegt — explizit fehlschlagen statt lautlos

    try:
        # Puffer leeren: veraltete /step/done Pakete verwerfen
        sock.settimeout(0.05)
        while True:
            try:
                sock.recvfrom(4096)
            except (socket.timeout, OSError):
                break

        # Request senden (eigener Send-Socket, nicht den Receive-Socket verwenden)
        msg = _build_osc_message("/devices/export", 1)
        sock.sendto(msg, (OSC_HOST, OSC_STEP_PORT))

        # Auf /devices/export/response warten — /step/done-Reste verwerfen
        sock.settimeout(timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(65535)
                addr_end = data.find(b"\x00")
                if addr_end < 0:
                    continue
                osc_addr = data[:addr_end].decode("ascii", errors="ignore")
                if osc_addr != "/devices/export/response":
                    continue  # veraltetes Paket — nächstes lesen
                tag_idx = data.find(b",s", addr_end)
                if tag_idx < 0:
                    return False
                str_start = tag_idx + 4
                null_pos = data.find(b"\x00", str_start)
                if null_pos <= str_start:
                    return False
                json_str = data[str_start:null_pos].decode("utf-8", errors="ignore")
                uuid_map: dict = _json.loads(json_str)

                _DEVICE_UUID_CACHE = {k.lower().strip(): v for k, v in uuid_map.items()}

                try:
                    from neo4j import GraphDatabase
                    driver = GraphDatabase.driver(
                        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
                    )
                    with driver.session() as s:
                        for name, uuid in uuid_map.items():
                            s.run(
                                "MERGE (d:Device {name: $name}) SET d.builtin_uuid = $uuid",
                                name=name, uuid=uuid,
                            )
                    driver.close()
                except Exception:
                    pass  # Neo4j nicht erreichbar — In-Memory-Cache reicht
                return True
            except (socket.timeout, OSError):
                break
        return False
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _build_osc_message(address: str, value: int) -> bytes:
    """Erstellt ein minimales OSC-Paket mit einem Integer-Argument."""
    import struct
    addr_bytes = address.encode("ascii") + b"\x00"
    addr_padded = addr_bytes + b"\x00" * ((4 - len(addr_bytes) % 4) % 4)
    type_tag = b",i\x00\x00"
    return addr_padded + type_tag + struct.pack(">i", value)


def _get_device_uuid_map() -> dict[str, str]:
    """Lädt alle Device-UUIDs.

    Reihenfolge (einmal pro Prozess):
      1. Extension via /devices/export — autoritativ, befüllt auch Neo4j
      2. Neo4j — wenn Extension nicht erreichbar (Bitwig nicht gestartet)
    Ab dem zweiten Aufruf: In-Memory-Cache.

    Returns: {lowercase_name: full_uuid_string}
    """
    global _DEVICE_UUID_CACHE, _SYNCED_FROM_EXTENSION
    if _DEVICE_UUID_CACHE is not None:
        return _DEVICE_UUID_CACHE

    # Extension ist primäre Quelle (einmal pro Prozess)
    if not _SYNCED_FROM_EXTENSION:
        if _sync_device_uuids_from_extension():
            _SYNCED_FROM_EXTENSION = True
            return _DEVICE_UUID_CACHE or {}

    # Fallback: Neo4j (wenn Extension/Bitwig nicht läuft)
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            result = s.run(
                "MATCH (n:Device) WHERE n.builtin_uuid IS NOT NULL "
                "RETURN n.name AS name, n.builtin_uuid AS uuid"
            )
            cache = {rec["name"].lower().strip(): rec["uuid"] for rec in result}
        driver.close()
        _DEVICE_UUID_CACHE = cache
    except Exception:
        _DEVICE_UUID_CACHE = {}
    return _DEVICE_UUID_CACHE


def _lookup_device_uuid(name: str) -> str | None:
    """Löst einen Gerätenamen in eine Bitwig-UUID auf.

    Strategie:
      1. Exakter Match (case-insensitive)
      2. Wort-Teilmenge: alle DB-Wörter im Query enthalten
         → "v9 Closed Hi-Hat" trifft "v9 Hat Closed" (hat+closed+v9 ⊆ {v9,closed,hi,hat})
         Bei Mehrfachtreffer gewinnt der längste (spezifischste) DB-Name.
      3. Präfix-Match: Query startet mit DB-Name
    """
    import re

    if not name:
        return None
    key = name.lower().strip()
    uuid_map = _get_device_uuid_map()

    if key in uuid_map:
        return uuid_map[key]

    def _words(s: str) -> frozenset:
        return frozenset(re.sub(r"[^a-z0-9]", " ", s.lower()).split())

    key_words = _words(name)
    best_uuid: str | None = None
    best_len = 0
    for db_name, uuid in uuid_map.items():
        db_words = _words(db_name)
        if db_words and db_words <= key_words and len(db_words) > best_len:
            best_uuid = uuid
            best_len = len(db_words)

    if best_uuid:
        return best_uuid

    # Overlap-Score: Treffer wenn >= 2 gemeinsame Wörter und alle Hauptwörter des
    # kürzeren Namens enthalten sind (fängt "v9 Hi-Hat" → "v9 Hat Closed" ab)
    _IGNORE = {"hi", "lo", "the", "a"}
    key_sig = key_words - _IGNORE
    for db_name, uuid in uuid_map.items():
        db_words = _words(db_name)
        db_sig = db_words - _IGNORE
        if not db_sig:
            continue
        overlap = key_sig & db_sig
        if len(overlap) >= 2 and overlap >= db_sig:
            return uuid

    for db_name, uuid in uuid_map.items():
        if db_name.startswith(key):
            return uuid

    # Reverse-Subset: key_words ⊆ db_words (Query allgemeiner als DB-Name, z.B. "Hi-Hat" → "v9 Hi-Hat")
    # Nur wenn key >= 1 signifikantes Wort (nicht "hi"/"lo" allein) um false positives zu vermeiden
    if key_sig:
        rev_best_uuid: str | None = None
        rev_best_extra = 999  # DB-Name mit wenigsten Extra-Wörtern gewinnt
        for db_name, uuid in uuid_map.items():
            db_words = _words(db_name)
            db_sig = db_words - _IGNORE
            if key_sig <= db_sig:  # alle Query-Wörter im DB-Namen enthalten
                extra = len(db_sig) - len(key_sig)
                if extra < rev_best_extra:
                    rev_best_uuid = uuid
                    rev_best_extra = extra
        if rev_best_uuid:
            return rev_best_uuid

    return None


def invalidate_device_uuid_cache() -> None:
    """Cache leeren — erzwingt Extension-Sync beim nächsten Lookup."""
    global _DEVICE_UUID_CACHE, _SYNCED_FROM_EXTENSION
    _DEVICE_UUID_CACHE = None
    _SYNCED_FROM_EXTENSION = False


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
    """Holt Note-Counts pro Track via OSC (/clip/note/count/all).

    Fragt BitwigStepPlugin (Port 8002) — dort liegt der noteCountMap.
    Returns: {"v9 Kick": 8, "v9 Snare": 8, ...} oder {} wenn nicht erreichbar.
    """
    import socket, struct
    from pythonosc import udp_client as _udp
    client = _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT, allow_broadcast=False)
    sock = client._sock
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
        total = struct.unpack(">i", data[count_start : count_start + 4])[0]
        str_start = count_start + 4
        null_pos = data.find(b"\x00", str_start)
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
        try:
            sock.close()
        except Exception:
            pass


def _reset_note_counts() -> None:
    """Setzt noteCountMap im BitwigStepPlugin zurück (Port 8002)."""
    from pythonosc import udp_client as _udp
    client = _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT)
    try:
        client.send_message("/clip/note/count/reset", 1)
    except Exception:
        pass
    finally:
        try:
            client._sock.close()
        except Exception:
            pass


def _clear_all_tracks(timeout: float = 5.0) -> int:
    """Löscht alle Instrument-Tracks in Bitwig via /agent/tracks/clear.

    Wartet auf ACK (/agent/tracks/clear/response) — die Java-Extension löscht
    Tracks sequenziell mit 80ms Delay pro Track, ACK kommt nach allen Löschungen.
    Nach dem ACK wird der Track-Count verifiziert; verbleibende Tracks werden
    per Fallback einzeln gelöscht.
    Gibt Anzahl tatsächlich gelöschter Tracks zurück (0 wenn Bridge nicht erreichbar).
    """
    import socket, struct
    client = _bound_osc_client(timeout=timeout)
    reported = 0
    try:
        client.send_message("/agent/tracks/clear", 1)
        data, _ = client._sock.recvfrom(512)
        raw = data.decode("latin-1")
        tag_idx = raw.find(",i")
        if tag_idx >= 0:
            padded = (tag_idx + 4) & ~3
            if padded + 4 <= len(data):
                reported = struct.unpack(">i", data[padded : padded + 4])[0]
    except (socket.timeout, OSError):
        pass
    finally:
        try:
            client._sock.close()
        except Exception:
            pass

    # Kurze Pause dann verifizieren — Bitwig braucht ggf. noch einen Moment
    time.sleep(0.3)
    remaining = _get_current_track_count()
    if remaining > 0:
        # Fallback: verbleibende Tracks einzeln sequenziell löschen
        from pythonosc import udp_client as _udp
        fb = _udp.SimpleUDPClient(OSC_HOST, OSC_PORT)
        for _ in range(remaining):
            fb.send_message("/track/1/select", 1)
            time.sleep(0.15)
            fb.send_message("/track/delete/last", 1)
            time.sleep(0.25)
        _reset_note_counts()
        return reported + remaining

    return reported


def _get_track_names() -> list[str]:
    """Holt aktuelle Track-Namen via OSC (/agent/track/count).

    Returns: ["v9 Kick", "v9 Snare", "Phase-4", ...] oder [] wenn nicht erreichbar.
    """
    import socket, struct
    client = _bound_osc_client(timeout=2.0)
    try:
        client.send_message("/agent/track/count", 1)
        data, _ = client._sock.recvfrom(4096)
        raw = data.decode("latin-1")
        idx_s = raw.find(",is")
        if idx_s >= 0:
            str_start = idx_s + 8
            null_pos  = data.find(b"\x00", str_start)
            if null_pos > str_start:
                names_str = data[str_start:null_pos].decode("utf-8", errors="ignore")
                return [n.strip() for n in names_str.split(",") if n.strip()]
    except (socket.timeout, OSError):
        pass
    finally:
        try:
            client._sock.close()
        except Exception:
            pass
    return []


def _get_current_track_count() -> int:
    """Holt aktuelle Track-Anzahl via OSC. Gibt 0 zurück wenn nicht erreichbar."""
    import socket, struct
    client = _bound_osc_client(timeout=1.5)
    try:
        client.send_message("/agent/track/count", 1)
        data, _ = client._sock.recvfrom(512)
        raw = data.decode("latin-1")
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
        try:
            client._sock.close()
        except Exception:
            pass
    return 0


def _check_bridge(timeout: float = 1.5) -> bool:
    """Ping/Pong Verbindungstest. Meldet Fehler an Circuit Breaker."""
    import socket
    from src.agent.osc.circuit_breaker import get_circuit

    circuit = get_circuit()
    client = _bound_osc_client(timeout=timeout)
    sock = client._sock
    try:
        client.send_message("/ping", 1)
        sock.recvfrom(64)
        circuit._on_success()
        return True
    except (socket.timeout, OSError):
        circuit._on_failure()
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


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
        except Exception: pass

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
        except Exception: pass

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
