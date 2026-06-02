"""
Device-UUID Lookup — Extension → Neo4j → In-Memory Cache.

Alle UUID-Auflösungsfunktionen in einem Modul; kein @tool-Decorator.
"""
from __future__ import annotations
import os
import re

from dotenv import load_dotenv
load_dotenv()

OSC_HOST            = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_STEP_PORT       = int(os.getenv("BITWIG_STEP_PORT",       "8002"))
OSC_STEP_REPLY_PORT = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002"))

_DEVICE_UUID_CACHE: dict[str, str] | None = None
_SYNCED_FROM_EXTENSION = False


def _build_osc_message(address: str, value: int) -> bytes:
    import struct
    addr_bytes  = address.encode("ascii") + b"\x00"
    addr_padded = addr_bytes + b"\x00" * ((4 - len(addr_bytes) % 4) % 4)
    return addr_padded + b",i\x00\x00" + struct.pack(">i", value)


def _sync_device_uuids_from_extension(timeout: float = 3.0) -> bool:
    """Holt BUILTIN_UUIDS von BitwigStepPlugin via /devices/export, schreibt nach Neo4j."""
    global _DEVICE_UUID_CACHE
    import socket
    import json as _json
    from pythonosc import udp_client as _udp

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError:
        sock.close()
        return False

    try:
        _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT).send_message("/devices/export", 1)
        sock.settimeout(timeout)
        deadline = __import__("time").time() + timeout
        while __import__("time").time() < deadline:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                break
            addr_end = data.find(b"\x00")
            if addr_end < 0:
                continue
            osc_addr = data[:addr_end].decode("ascii", errors="ignore")
            if osc_addr != "/devices/export/response":
                continue
            tag_start = (addr_end + 4) & ~3
            if tag_start + 2 >= len(data) or data[tag_start:tag_start + 2] != b",s":
                break
            str_start = (tag_start + 4) & ~3
            null_pos  = data.find(b"\x00", str_start)
            if null_pos <= str_start:
                break
            json_str = data[str_start:null_pos].decode("utf-8", errors="ignore")
            try:
                raw_map: dict[str, str] = _json.loads(json_str)
            except Exception:
                break
            cache = {k.lower().strip(): v for k, v in raw_map.items()}
            _DEVICE_UUID_CACHE = cache
            _write_uuids_to_neo4j(cache)
            return True
    except Exception:
        pass
    finally:
        sock.close()
    return False


def _write_uuids_to_neo4j(uuid_map: dict[str, str]) -> None:
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
        pass


def _get_device_uuid_map() -> dict[str, str]:
    global _DEVICE_UUID_CACHE, _SYNCED_FROM_EXTENSION
    if _DEVICE_UUID_CACHE is not None:
        return _DEVICE_UUID_CACHE
    if not _SYNCED_FROM_EXTENSION:
        if _sync_device_uuids_from_extension():
            _SYNCED_FROM_EXTENSION = True
            return _DEVICE_UUID_CACHE or {}
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

    _IGNORE = {"hi", "lo", "the", "a"}
    key_sig = key_words - _IGNORE
    for db_name, uuid in uuid_map.items():
        db_words = _words(db_name)
        db_sig   = db_words - _IGNORE
        if not db_sig:
            continue
        overlap = key_sig & db_sig
        if len(overlap) >= 2 and overlap >= db_sig:
            return uuid

    for db_name, uuid in uuid_map.items():
        if db_name.startswith(key):
            return uuid

    if key_sig:
        rev_best_uuid: str | None = None
        rev_best_extra = 999
        for db_name, uuid in uuid_map.items():
            db_words = _words(db_name)
            db_sig   = db_words - _IGNORE
            if key_sig <= db_sig:
                extra = len(db_sig) - len(key_sig)
                if extra < rev_best_extra:
                    rev_best_uuid = uuid
                    rev_best_extra = extra
        if rev_best_uuid:
            return rev_best_uuid

    return None


def invalidate_device_uuid_cache() -> None:
    global _DEVICE_UUID_CACHE, _SYNCED_FROM_EXTENSION
    _DEVICE_UUID_CACHE = None
    _SYNCED_FROM_EXTENSION = False
