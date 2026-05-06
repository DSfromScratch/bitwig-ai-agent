#!/usr/bin/env python3
"""
Bitwig Browser Scanner — scannt alle Devices aus dem laufenden Bitwig Studio
und ingested sie mit korrekten Namen in die Neo4j Wissensdatenbank.

Voraussetzung:
  - Bitwig Studio läuft + BitwigAgentBridge.bwextension aktiv (Port 8001)
  - Neo4j läuft (bolt://localhost:7687)
  - python -m venv .venv && pip install python-osc neo4j

Aufruf:
  python scripts/scan_bitwig_devices.py                  # vollständiger Scan
  python scripts/scan_bitwig_devices.py --search kick    # nur Kick-Varianten anzeigen
  python scripts/scan_bitwig_devices.py --genre Nu-Metal # Nu-Metal in DB anlegen
  python scripts/scan_bitwig_devices.py --dry-run        # nur anzeigen, nichts speichern
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pythonosc import udp_client

OSC_HOST = "127.0.0.1"
OSC_PORT = 8001

# Datei-Pfade: Java schreibt unter Windows, Python liest unter WSL
CATALOG_WIN = r"C:\Users\Public\bitwig_catalog.json"
CATALOG_WSL = "/mnt/c/Users/Public/bitwig_catalog.json"


# ── OSC Hilfsfunktionen ───────────────────────────────────────────────────────

def osc(address: str, value=1):
    udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT).send_message(address, value)

def osc_str(address: str, value: str):
    udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT).send_message(address, value)


# ── Browser-Scan ──────────────────────────────────────────────────────────────

def scan_browser_catalog() -> list[dict]:
    """
    Öffnet Bitwig Device-Browser, wartet auf Katalog-Aufbau,
    speichert als JSON, schließt Browser, gibt Einträge zurück.
    """
    print("▶ Browser öffnen...")
    osc("/browser/device", 1)
    print("  Warte 3s auf Katalog-Aufbau...")
    time.sleep(3.0)

    print(f"▶ Katalog speichern → {CATALOG_WIN}")
    osc_str("/browser/catalog/save", CATALOG_WIN)
    time.sleep(0.8)

    osc("/browser/cancel", 1)
    time.sleep(0.3)

    if not Path(CATALOG_WSL).exists():
        print(f"✗ Katalog nicht gefunden: {CATALOG_WSL}")
        print("  Bitwig + BitwigAgentBridge aktiv?")
        return []

    with open(CATALOG_WSL) as f:
        catalog = json.load(f)

    print(f"  → {len(catalog)} Einträge gefunden")
    return catalog


# ── Automatische Kategorisierung ──────────────────────────────────────────────

DRUM_KEYS  = ("e-kick", "e-snare", "e-hi-hat", "e-hihat", "e-tom",
               "e-clap", "e-cowbell")
SYNTH_KEYS = ("polymer", "phase-4", "fm-4", "polysynth", "sampler",
               "drum machine", "operators", "instrument layer", "note expression")
FX_KEYS    = ("distortion", "saturator", "compressor", "eq-5", "eq-2",
               "delay-2", "delay-1", "reverb", "ladder filter",
               "transient control", "limiter", "flanger", "freq shifter",
               "pitch shifter", "amp designer", "cabinet", "bit-8",
               "ring mod", "gate", "comb filter", "rotary", "chorus",
               "multiband", "spectral", "mid-side")


def categorize(name: str) -> tuple[str, str, str]:
    """Gibt (type, category, browser_path) zurück."""
    key = name.lower()
    if any(k in key for k in DRUM_KEYS):
        return "instrument", "drum_synth", f"Instruments > Drums > {name}"
    if any(k in key for k in SYNTH_KEYS):
        return "instrument", "synthesizer", f"Instruments > Synthesizers > {name}"
    if any(k in key for k in FX_KEYS):
        return "effect", "audio_fx", f"Devices > Audio FX > {name}"
    return "instrument", "other", f"Instruments > {name}"


# ── Neo4j Ingest ──────────────────────────────────────────────────────────────

def ingest_devices(catalog: list[dict]) -> int:
    from src.knowledge.neo4j_graph import session
    count = 0
    with session() as s:
        for entry in catalog:
            name = entry["name"]
            dtype, cat, bpath = categorize(name)
            s.run("""
                MERGE (d:Device {name: $name})
                SET d.type=$type, d.category=$category, d.browser_path=$bpath
            """, name=name, type=dtype, category=cat, bpath=bpath)
            count += 1
    return count


# ── Nu-Metal Genre Setup ───────────────────────────────────────────────────────

# Rollen-Zuordnung: (Suchbegriffe im Devicenamen, Rolle, Gewicht)
NU_METAL_ROLES: list[tuple[list[str], str, float]] = [
    (["e-kick"],                         "drums",       0.95),
    (["e-snare"],                        "drums",       0.90),
    (["e-hi-hat", "e-hihat", "hihat"],   "drums",       0.80),
    (["distortion"],                     "guitar_fx",   0.92),
    (["saturator"],                      "bass_fx",     0.85),
    (["amp designer", "cabinet", "amp"], "guitar_amp",  0.88),
    (["compressor"],                     "dynamics",    0.88),
    (["fm-4", "fm4"],                    "bass_synth",  0.80),
    (["eq-5", "eq5"],                    "eq",          0.75),
    (["delay"],                          "fx",          0.65),
    (["reverb"],                         "fx",          0.60),
]


def setup_nu_metal_genre(device_names: list[str], dry_run: bool = False) -> None:
    """Legt Nu-Metal Genre an und verknüpft alle passenden Devices."""
    from src.knowledge.neo4j_graph import session

    print("\n▶ Nu-Metal Genre in Neo4j anlegen...")
    names_lower = {n.lower(): n for n in device_names}

    if not dry_run:
        with session() as s:
            s.run("""
                MERGE (g:Genre {name: 'Nu-Metal'})
                SET g.bpm_min=120, g.bpm_max=160,
                    g.key_mode='minor',
                    g.description='Heavy guitar riffs, Drop D tuning, hip-hop elements, aggressive drums'
            """)
        print("  ✓ Genre 'Nu-Metal' erstellt")

    linked = 0
    for terms, role, weight in NU_METAL_ROLES:
        matches = []
        for term in terms:
            matches = [orig for low, orig in names_lower.items() if term in low]
            if matches:
                break  # ersten Treffer pro Rolle nehmen

        for device in matches[:1]:  # max. 1 Device pro Rolle
            print(f"  {'→' if not dry_run else '~'} Nu-Metal --[{role}, w={weight}]--> {device}")
            if not dry_run:
                with session() as s:
                    s.run("""
                        MATCH (g:Genre {name: 'Nu-Metal'}), (d:Device {name: $device})
                        MERGE (g)-[r:USES {role: $role}]->(d)
                        SET r.weight = $weight
                    """, device=device, role=role, weight=weight)
            linked += 1

    if linked == 0:
        print("  ⚠ Keine passenden Devices im Katalog — Browser-Scan korrekt?")
    else:
        print(f"  → {linked} Devices verknüpft")


# ── Hauptprogramm ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bitwig Browser Scanner & Neo4j Ingest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--search",   metavar="TERM",
                        help="Nur Devices mit diesem Begriff anzeigen")
    parser.add_argument("--genre",    default="Nu-Metal",
                        help="Genre für DB-Setup (default: Nu-Metal)")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Nur anzeigen, nichts in DB schreiben")
    parser.add_argument("--no-ingest", action="store_true",
                        help="Scan durchführen aber nicht in DB schreiben")
    args = parser.parse_args()

    # 1. Browser scannen
    catalog = scan_browser_catalog()
    if not catalog:
        sys.exit(1)

    names = sorted(e["name"] for e in catalog)

    # 2. Anzeigen / filtern
    if args.search:
        hits = [n for n in names if args.search.lower() in n.lower()]
        print(f"\nSuche '{args.search}' ({len(hits)} Treffer):")
        for n in hits:
            dtype, cat, _ = categorize(n)
            print(f"  - {n:30s} [{dtype}/{cat}]")
    else:
        print(f"\nAlle Devices ({len(names)}):")
        for n in names:
            dtype, cat, _ = categorize(n)
            print(f"  {n:30s} [{dtype}/{cat}]")

    if args.dry_run or args.no_ingest:
        print("\n(--dry-run / --no-ingest: kein DB-Write)")
        if args.genre:
            setup_nu_metal_genre(names, dry_run=True)
        return

    # 3. In Neo4j ingesten
    print(f"\n▶ Ingesting {len(catalog)} Devices in Neo4j...")
    count = ingest_devices(catalog)
    print(f"  ✓ {count} Devices gespeichert")

    # 4. Genre anlegen
    if args.genre:
        setup_nu_metal_genre(names)

    print("\n✓ Fertig!")


if __name__ == "__main__":
    main()
