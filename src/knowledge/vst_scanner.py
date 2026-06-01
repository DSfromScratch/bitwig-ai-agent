"""
VST Plugin Scanner — Bitwig → Neo4j.

Scannt alle installierten VST3-Plugins via BitwigStepPlugin OSC (/plugins/scan),
speichert sie als InstalledPlugin-Knoten in Neo4j und stellt eine Query-Funktion bereit.
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

def scan_installed_plugins(timeout: float = 5.0) -> list[str]:
    """Fragt BitwigStepPlugin nach allen installierten VST3-Plugins.

    Returns: Liste von Plugin-Namen z.B. ["Surge XT", "Dexed", "VB-ROYAL", ...]
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
                data, _ = sock.recvfrom(4096)
                addr_end = data.find(b"\x00")
                if addr_end < 0:
                    continue
                osc_addr = data[:addr_end].decode("ascii", errors="ignore")
                if osc_addr == "/plugins/scan/response":
                    # OSC String parsen
                    tag_start = (addr_end + 4) & ~3
                    if tag_start + 2 < len(data) and data[tag_start:tag_start+2] == b",s":
                        str_start = (tag_start + 4) & ~3
                        null_pos  = data.find(b"\x00", str_start)
                        raw = data[str_start:null_pos].decode("utf-8", errors="ignore") if null_pos > str_start else ""
                        all_items = [p.strip() for p in raw.split(",") if p.strip()]
                        # VST3-Plugins: bekannte Hersteller-Prefixe + bekannte Produktnamen
                        # Bitwig-Presets ("Abyssal Plain", "Accept Data" etc.) werden ausgeschlossen
                        vst_prefixes = (
                            "VB-", "VD-", "VG-", "VI-",   # UJAM Virtual series
                            "Surge", "Dexed", "OB-Xd",    # Open-source Synths
                            "MT-Power", "MT-",             # MT Audio
                            "Decent", "Spitfire", "LABS",  # Sample players
                            "Kontakt", "Massive", "Serum", "Vital",  # Native/Xfer/Matt
                            "Amplitube", "TRacks",         # IK Multimedia
                            "Waves ", "UAD-",              # Waves, Universal Audio
                            "FabFilter", "iZotope",        # FabFilter, iZotope
                            "Neural ", "AIDA-X",           # Neural Amp Modeler
                            "sfizz", "DrumGizmo",          # Open source
                        )
                        plugins = [
                            p for p in all_items
                            if any(p.startswith(pf) or p.lower().startswith(pf.lower())
                                   for pf in vst_prefixes)
                        ]
                        log.info("VST-Scan: %d/%d Items als VST3-Plugins erkannt", len(plugins), len(all_items))
                        return plugins
            except socket.timeout:
                break
    finally:
        sock.close()
    return []


# ── Neo4j Storage ─────────────────────────────────────────────────────────────

_UJAM_TYPES = {
    "VD-": "drums", "VB-": "bass", "VG-": "guitar",
    "VI-": "instrument",
}

_KNOWN_TYPES = {
    "Surge XT": "synth",     "Surge XT Effects": "effect",
    "Dexed": "synth",        "OB-Xd Legacy": "synth",
    "MT-PowerDrumKit": "drums",
}

def _guess_type(name: str) -> str:
    upper = name.upper()
    for prefix, t in _UJAM_TYPES.items():
        if upper.startswith(prefix):
            return t
    return _KNOWN_TYPES.get(name, "instrument")


def store_plugins_neo4j(plugins: list[str]) -> int:
    """Speichert VST-Plugin-Liste als InstalledPlugin-Knoten in Neo4j.

    Returns: Anzahl gespeicherter Knoten.
    """
    try:
        from neo4j import GraphDatabase
    except ImportError:
        log.warning("neo4j package nicht installiert")
        return 0

    neo4j_uri  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER",     "neo4j")
    neo4j_pass = os.getenv("NEO4J_PASSWORD", "neo4jllm")

    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
        with driver.session() as s:
            # Schema sicherstellen
            s.run("CREATE CONSTRAINT installed_plugin_name IF NOT EXISTS "
                  "FOR (p:InstalledPlugin) REQUIRE p.name IS UNIQUE")
            # Zuerst alle als not_installed markieren
            s.run("MATCH (p:InstalledPlugin) SET p.installed = false")
            # Aktuelle Liste eintragen
            for name in plugins:
                plugin_type = _guess_type(name)
                s.run(
                    "MERGE (p:InstalledPlugin {name: $name}) "
                    "SET p.type = $type, p.installed = true, p.format = 'VST3'",
                    name=name, type=plugin_type
                )
        driver.close()
        log.info("Neo4j: %d InstalledPlugin-Knoten gespeichert", len(plugins))
        return len(plugins)
    except Exception as e:
        log.warning("Neo4j-Fehler beim Speichern: %s", e)
        return 0


def query_installed_plugins(plugin_type: str | None = None) -> list[dict]:
    """Liest installierte VST-Plugins aus Neo4j.

    Args:
        plugin_type: "drums", "bass", "guitar", "synth", "instrument" oder None für alle
    Returns:
        Liste von {"name": str, "type": str}
    """
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return []

    neo4j_uri  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER",     "neo4j")
    neo4j_pass = os.getenv("NEO4J_PASSWORD", "neo4jllm")

    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
        with driver.session() as s:
            if plugin_type:
                result = s.run(
                    "MATCH (p:InstalledPlugin {installed: true, type: $type}) "
                    "RETURN p.name AS name, p.type AS type ORDER BY p.name",
                    type=plugin_type
                )
            else:
                result = s.run(
                    "MATCH (p:InstalledPlugin {installed: true}) "
                    "RETURN p.name AS name, p.type AS type ORDER BY p.type, p.name"
                )
            plugins = [{"name": r["name"], "type": r["type"]} for r in result]
        driver.close()
        return plugins
    except Exception as e:
        log.warning("Neo4j-Fehler beim Lesen: %s", e)
        return []


# ── Haupt-Funktion: Scan + Store ──────────────────────────────────────────────

def scan_and_store() -> str:
    """Scannt VSTs aus Bitwig und speichert in Neo4j. Gibt Zusammenfassung zurück."""
    plugins = scan_installed_plugins()
    if not plugins:
        return "Kein VST gefunden — Bitwig läuft? BitwigStepPlugin aktiv?"

    stored = store_plugins_neo4j(plugins)
    by_type: dict[str, list[str]] = {}
    for p in plugins:
        t = _guess_type(p)
        by_type.setdefault(t, []).append(p)

    lines = [f"{len(plugins)} VST3-Plugins gescannt und in Neo4j gespeichert:"]
    for t, names in sorted(by_type.items()):
        lines.append(f"  {t}: {', '.join(names)}")
    return "\n".join(lines)
