"""
VST Plugin Scanner — Bitwig → Neo4j.

Scannt alle installierten Instrument-Plugins via BitwigStepPlugin OSC (/plugins/scan),
speichert sie als Device-Knoten in Neo4j (category + device_type='instrument').
"""
from __future__ import annotations

import os
import socket
import time
import logging

from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger(__name__)

OSC_HOST            = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_STEP_PORT       = int(os.getenv("BITWIG_STEP_PORT",       "8002"))
OSC_STEP_REPLY_PORT = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002"))


# ── Scan via OSC ──────────────────────────────────────────────────────────────

def scan_installed_plugins(timeout: float = 8.0) -> list[str]:
    """/plugins/scan öffnet den Bitwig-Browser im Instrument-Kontext → nur Instrumente.

    Returns: Liste von Plugin-Namen z.B. ["Arturia Bass V3", "Surge XT", ...]
    """
    from pythonosc import udp_client as _udp

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try: sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError: pass
    sock.settimeout(timeout)
    try:
        sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError:
        pass

    try:
        _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT).send_message("/plugins/scan", 1)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(65535)
                addr_end = data.find(b"\x00")
                if addr_end < 0:
                    continue
                osc_addr = data[:addr_end].decode("ascii", errors="ignore")
                if osc_addr == "/plugins/scan/response":
                    tag_start = (addr_end + 4) & ~3
                    if tag_start + 2 < len(data) and data[tag_start:tag_start+2] == b",s":
                        str_start = (tag_start + 4) & ~3
                        null_pos  = data.find(b"\x00", str_start)
                        raw = data[str_start:null_pos].decode("utf-8", errors="ignore") if null_pos > str_start else ""
                        plugins = [p.strip() for p in raw.split(",") if p.strip()]
                        log.info("VST-Scan: %d Instrument-Plugins empfangen", len(plugins))
                        return plugins
            except socket.timeout:
                break
    finally:
        sock.close()
    return []


# ── Kategorisierung ───────────────────────────────────────────────────────────

_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("bass station", "mini v", "moog bass",),              "bass"),
    (("arturia bass", "vb-",),                              "bass"),
    (("arturia piano", "piano v", "stage-73", "wurli",
      "clavinet", "mellotron", "keyscape",),                "piano"),
    (("arturia", "analog lab", "prophet", "jup-", "arp ",
      "ob-xd", "cs-80", "buchla", "jun-6",
      "surge", "dexed", "vital", "helm", "serum",
      "massive", "sylenth", "phase-4", "polysynth",),       "synthesizer"),
    (("vd-",),                                              "drums"),
    (("mt-power", "drumgizmo", "battery",
      "superior drummer", "ezdrummer",),                    "drums"),
    (("vg-", "neural dsp", "amplitube", "bias amp",),       "guitar"),
    (("kontakt", "komplete", "spitfire", "labs",
      "decent sampler", "sfizz",),                          "sampler"),
    (("omnisphere", "trilian",),                            "keys"),
]

_EFFECT_SKIP = frozenset([
    "reverb", "delay", "compressor", "limiter", " eq", "equalizer",
    "chorus", "flanger", "phaser", "distortion", "saturator", "gate ",
    "de-esser", "transient", "exciter", "multiband", "maximizer",
])


def _guess_category(name: str) -> str:
    lower = name.lower()
    if any(kw in lower for kw in _EFFECT_SKIP):
        return "effect"
    for keywords, cat in _CATEGORY_RULES:
        if any(lower.startswith(kw) or kw in lower for kw in keywords):
            return cat
    return "synthesizer"


# ── Neo4j Storage ─────────────────────────────────────────────────────────────

def store_plugins_neo4j(plugins: list[str]) -> int:
    """Schreibt Plugins als Device-Knoten in Neo4j (für _fetch_instrument_list)."""
    from src.knowledge.neo4j_graph import session as _session

    try:
        with _session() as s:
            s.run("CREATE CONSTRAINT installed_plugin_name IF NOT EXISTS "
                  "FOR (p:InstalledPlugin) REQUIRE p.name IS UNIQUE")
            s.run("MATCH (p:InstalledPlugin) SET p.installed = false")

            saved = 0
            for name in plugins:
                cat = _guess_category(name)
                if cat == "effect":
                    continue
                s.run(
                    "MERGE (d:Device {name: $name}) "
                    "SET d.category = $cat, d.device_type = 'instrument', d.source = 'scan'",
                    name=name, cat=cat,
                )
                s.run(
                    "MERGE (p:InstalledPlugin {name: $name}) "
                    "SET p.type = $cat, p.installed = true, p.format = 'VST3'",
                    name=name, cat=cat,
                )
                saved += 1

        log.info("Neo4j: %d Instrument-Plugins gespeichert", saved)
        return saved
    except Exception as exc:
        log.warning("Neo4j-Fehler: %s", exc)
        return 0


def query_installed_plugins(plugin_type: str | None = None) -> list[dict]:
    """Liest installierte VST-Plugins aus Neo4j."""
    from src.knowledge.neo4j_graph import session as _session
    try:
        with _session() as s:
            if plugin_type:
                result = s.run(
                    "MATCH (p:InstalledPlugin {installed: true, type: $type}) "
                    "RETURN p.name AS name, p.type AS type ORDER BY p.name",
                    type=plugin_type,
                )
            else:
                result = s.run(
                    "MATCH (p:InstalledPlugin {installed: true}) "
                    "RETURN p.name AS name, p.type AS type ORDER BY p.type, p.name"
                )
            return [{"name": r["name"], "type": r["type"]} for r in result]
    except Exception as exc:
        log.warning("Neo4j-Fehler: %s", exc)
        return []


def scan_and_store() -> str:
    """Scannt Instrument-Plugins aus Bitwig und speichert in Neo4j."""
    plugins = scan_installed_plugins()
    if not plugins:
        return "Kein Plugin gefunden — Bitwig läuft? BitwigStepPlugin aktiv?"

    saved = store_plugins_neo4j(plugins)
    by_cat: dict[str, list[str]] = {}
    for p in plugins:
        cat = _guess_category(p)
        if cat != "effect":
            by_cat.setdefault(cat, []).append(p)

    lines = [f"{saved} Instrument-Plugins gescannt und in Neo4j gespeichert:"]
    for cat, names in sorted(by_cat.items()):
        lines.append(f"  {cat}: {', '.join(names)}")
    return "\n".join(lines)
