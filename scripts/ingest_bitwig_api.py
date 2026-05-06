#!/usr/bin/env python3
"""
Extrahiert die Bitwig Controller API (v25) aus dem JAR via javap
und schreibt alle Klassen + Methoden als strukturierte Nodes in Neo4j.

Nodes:
  (:APIClass  {name, package, description, api_version})
  (:APIMethod {name, signature, returns, params, description})

Beziehungen:
  (:APIClass)-[:HAS_METHOD]->(:APIMethod)
  (:APIClass)-[:EXTENDS]->(:APIClass)

Usage:
  python scripts/ingest_bitwig_api.py
  python scripts/ingest_bitwig_api.py --classes Browser Clip Transport
"""

import subprocess
import re
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

JAR_PATH = next(Path.home().glob(".m2/**/extension-api-25.jar"), None)
NEO4J_URI  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD", "neo4jllm")

# Klassen die für unsere Bitwig-Bridge relevant sind
RELEVANT_CLASSES = [
    # Browser
    "PopupBrowser", "BrowserItem", "BrowserFilterItem", "BrowserFilterColumn",
    "BrowserResultsItem", "BrowserResultsColumn", "BrowserItemBank",
    "BrowserFilterItemBank", "BrowserResultsItemBank", "BrowserColumn",
    # Devices & Tracks
    "CursorDevice", "Device", "DeviceBank", "Track", "TrackBank",
    "CursorTrack", "Channel", "ChannelBank",
    # Clips & Launcher
    "ClipLauncherSlot", "ClipLauncherSlotBank", "ClipLauncherSlotOrScene",
    "CursorClip", "Clip", "SceneBank", "Scene",
    # Transport & Host
    "Transport", "ControllerHost", "Application",
    # Values
    "SettableBooleanValue", "BooleanValue", "StringValue", "SettableStringValue",
    "IntegerValue", "SettableIntegerValue", "DoubleValue",
    # Cursor
    "CursorRemoteControlsPage", "RemoteControl",
    # OSC
]

# Menschenlesbare Beschreibungen für die wichtigsten Klassen
CLASS_DOCS = {
    "PopupBrowser": (
        "Browser-Dialog der sich öffnet wenn Geräte oder Presets eingefügt werden. "
        "Wichtigste Methoden: commit() (OK-Button), cancel() (Abbrechen), "
        "selectFirstFile(), selectNextFile() (Ergebnisliste navigieren), "
        "categoryColumn(), smartCollectionColumn() (Filter-Spalten). "
        "WICHTIG: commit() und selectFirstFile() funktionieren NUR aus OSC-Handlern, "
        "NICHT aus flush()."
    ),
    "BrowserItem": (
        "Einzelner Eintrag in einer Browser-Spalte. "
        "name() → StringValue (Anzeigename), exists() → BooleanValue, "
        "isSelected() → SettableBooleanValue. "
        "isSelected().set(true) selektiert das Item — funktioniert für Filter-Spalten "
        "aber NICHT als Click-Ersatz in der Ergebnisliste."
    ),
    "BrowserFilterColumn": (
        "Linke Filterspaltenim Browser (Kategorie, Collection, Hersteller). "
        "createItemBank(size) → Bank mit Filter-Items. "
        "getWildcardItem() → 'Alle' Eintrag (Wildcard/Reset). "
        "Jedes Item: isSelected().set(true) aktiviert den Filter."
    ),
    "BrowserResultsColumn": (
        "Mittlere Ergebnisspalte im Browser. "
        "createItemBank(size) → Bank mit Ergebnis-Items. "
        "Navigation über PopupBrowser.selectFirstFile/selectNextFile, "
        "NICHT über Item.isSelected().set(true)."
    ),
    "CursorDevice": (
        "Cursor auf ein Device innerhalb eines Tracks. "
        "browseToInsertBeforeDevice() → öffnet Browser um Gerät VOR diesem einzufügen. "
        "browseToReplaceDevice() → öffnet Browser um dieses Gerät zu ersetzen. "
        "createCursorRemoteControlsPage(count) → 8 Remote-Parameter."
    ),
    "CursorTrack": (
        "Cursor der einem Track folgt. createLauncherCursorClip(steps, pitches) → "
        "CursorClip für Note-Editing. clipLauncherSlotBank() → Slot-Bank "
        "(nur wenn createCursorTrack mit numScenes > 0 erstellt!)."
    ),
    "ClipLauncherSlotBank": (
        "Bank von Clip-Slots eines Tracks. "
        "createEmptyClip(slot, lengthInBeats) → leeren Clip anlegen. "
        "select(slot) → Slot auswählen (CursorClip folgt). "
        "launch(slot) → Clip starten."
    ),
    "CursorClip": (
        "Editor für den aktuell selektierten Launcher-Clip. "
        "setStepSize(beats) → Raster (0.25 = 1/16). "
        "setStep(channel, step, pitch, velocity, durationBeats) → Note schreiben. "
        "clearStep(step, pitch) → Note löschen. clearSteps() → alle löschen. "
        "WICHTIG: step ist Step-Index (step = beat / stepSize). "
        "duration ist in BEATS, nicht in Steps."
    ),
    "Transport": (
        "Transport-Steuerung. tempo().setRaw(bpm) → Tempo. "
        "play(), stop(), record(). "
        "arrangerLoopStart(), arrangerLoopDuration() → Loop-Punkte. "
        "getPosition() → aktuelle Position."
    ),
    "ControllerHost": (
        "Haupt-Host-Objekt. createCursorTrack(id, name, numSends, numScenes, followSelection). "
        "WICHTIG: numScenes MUSS > 0 sein damit clipLauncherSlotBank() nicht null ist! "
        "createMainTrackBank(numTracks, numSends, numScenes). "
        "getOscModule() → OSC-Funktionen."
    ),
    "SceneBank": (
        "Bank von Scenes. launchScene(index) → startet alle Clips in dieser Scene. "
        "getScene(index) → einzelne Scene. "
        "Erstellt über: trackBank.sceneBank()."
    ),
}

METHOD_DOCS = {
    "PopupBrowser.commit": (
        "Drückt OK im Browser und fügt das selektierte Gerät/Preset ein. "
        "Muss aus einem OSC-Handler aufgerufen werden, NICHT aus flush(). "
        "Funktioniert nur wenn ein Item selektiert ist."
    ),
    "PopupBrowser.selectFirstFile": (
        "Navigiert zum ersten Ergebnis in der mittleren Spalte. "
        "Entspricht einem Klick auf den ersten Listeneintrag. "
        "Muss aus OSC-Handler aufgerufen werden."
    ),
    "PopupBrowser.selectNextFile": (
        "Navigiert zum nächsten Ergebnis (ein Schritt nach unten). "
        "Mit selectFirstFile() + N × selectNextFile() zu Position N navigieren."
    ),
    "CursorClip.setStep": (
        "Schreibt eine Note in den Clip. "
        "Parameter: channel (immer 0), step (Step-Index = beat/stepSize), "
        "pitch (MIDI 0-127), velocity (0-127 als int), duration (in Beats!). "
        "NICHT in Steps — duration=1.0 = eine Viertelnote."
    ),
    "ClipLauncherSlotBank.createEmptyClip": (
        "Erstellt einen leeren Clip. "
        "Parameter: slot (0-basiert), length (in BEATS). "
        "Bitwig API v25: length ist in Beats, nicht in Bars!"
    ),
}


def javap_class(class_name: str) -> str | None:
    """Führt javap auf eine Bitwig-API-Klasse aus."""
    full_name = f"com.bitwig.extension.controller.api.{class_name}"
    try:
        result = subprocess.run(
            ["javap", "-classpath", str(JAR_PATH), full_name],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None


def parse_methods(javap_output: str) -> list[dict]:
    """Parst Methoden aus javap-Output."""
    methods = []
    for line in javap_output.splitlines():
        line = line.strip()
        # Nur public abstract / public default Methoden
        if not line.startswith("public abstract") and not line.startswith("public default"):
            continue
        # Rückgabetyp und Methodenname extrahieren
        m = re.match(
            r"public (?:abstract |default )"
            r"(?:[\w.<>, ]+\s+)?"
            r"([\w.]+)\s*\(([^)]*)\)",
            line
        )
        if not m:
            continue

        full_match = re.match(
            r"public (?:abstract |default )([\w.<>?,\s\[\]]+)\s+([\w]+)\s*\(([^)]*)\)",
            line
        )
        if full_match:
            returns    = full_match.group(1).strip().split(".")[-1]  # kurzer Typ
            method_name = full_match.group(2).strip()
            params_raw = full_match.group(3).strip()
            params = [p.strip().split(".")[-1] for p in params_raw.split(",") if p.strip()]
        else:
            continue

        doc_key = f"{javap_output.splitlines()[0].split()[-1].split('.')[-1]}.{method_name}"
        methods.append({
            "name":      method_name,
            "returns":   returns,
            "params":    params,
            "signature": line[:200],
            "doc":       METHOD_DOCS.get(doc_key, ""),
        })
    return methods


def ingest_to_neo4j(classes_data: list[dict]) -> None:
    """Schreibt API-Daten in Neo4j."""
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    ingested = 0

    with driver.session() as s:
        # Constraints
        s.run("CREATE CONSTRAINT api_class_name IF NOT EXISTS FOR (c:APIClass) REQUIRE c.name IS UNIQUE")
        s.run("CREATE CONSTRAINT api_method_sig IF NOT EXISTS FOR (m:APIMethod) REQUIRE m.signature IS UNIQUE")

        for cls in classes_data:
            # APIClass Node
            s.run("""
                MERGE (c:APIClass {name: $name})
                SET c.package    = $package,
                    c.full_name  = $full_name,
                    c.description = $description,
                    c.api_version = 25
            """, name=cls["name"], package=cls["package"],
                 full_name=cls["full_name"], description=cls["description"])

            # APIMethod Nodes
            for m in cls["methods"]:
                sig = f"{cls['name']}.{m['name']}({','.join(m['params'])})"[:250]
                s.run("""
                    MERGE (m:APIMethod {signature: $sig})
                    SET m.name        = $name,
                        m.returns     = $returns,
                        m.params      = $params,
                        m.description = $doc,
                        m.class_name  = $cls
                    WITH m
                    MATCH (c:APIClass {name: $cls})
                    MERGE (c)-[:HAS_METHOD]->(m)
                """, sig=sig, name=m["name"], returns=m["returns"],
                     params=m["params"], doc=m["doc"], cls=cls["name"])

            ingested += 1
            print(f"  ✓ {cls['name']} ({len(cls['methods'])} Methoden)")

    driver.close()
    print(f"\nFertig: {ingested} Klassen in Neo4j")


def main():
    if not JAR_PATH:
        print("❌ extension-api-25.jar nicht gefunden")
        sys.exit(1)

    # Welche Klassen einlesen?
    target = sys.argv[1:] if len(sys.argv) > 1 else None
    classes_to_scan = target if target else RELEVANT_CLASSES

    print(f"Extrahiere {len(classes_to_scan)} API-Klassen aus {JAR_PATH.name}...")
    classes_data = []

    for cls_name in classes_to_scan:
        output = javap_class(cls_name)
        if not output:
            print(f"  ✗ {cls_name} nicht gefunden")
            continue

        methods = parse_methods(output)
        classes_data.append({
            "name":        cls_name,
            "package":     "com.bitwig.extension.controller.api",
            "full_name":   f"com.bitwig.extension.controller.api.{cls_name}",
            "description": CLASS_DOCS.get(cls_name, f"Bitwig Controller API: {cls_name}"),
            "methods":     methods,
        })

    if not classes_data:
        print("Keine Klassen extrahiert.")
        sys.exit(1)

    print(f"\nSchreibe {len(classes_data)} Klassen in Neo4j...")
    ingest_to_neo4j(classes_data)

    # KnowledgeQA-Einträge für wichtige Klassen erstellen
    print("\nErstelle KnowledgeQA-Einträge...")
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    with driver.session() as s:
        for cls_name, doc in CLASS_DOCS.items():
            text = f"Q: Wie funktioniert {cls_name} in der Bitwig Controller API?\n\nA: {doc}"
            s.run("""
                MERGE (k:KnowledgeQA {source: 'BitiwgAPI_v25', text: $text})
                SET k.class = $cls
            """, text=text, cls=cls_name)
        for method_key, doc in METHOD_DOCS.items():
            text = f"Q: Was macht {method_key} in der Bitwig Controller API?\n\nA: {doc}"
            s.run("""
                MERGE (k:KnowledgeQA {source: 'BitiwgAPI_v25', text: $text})
                SET k.method = $m
            """, text=text, m=method_key)
    driver.close()
    print("✓ KnowledgeQA-Einträge erstellt")


if __name__ == "__main__":
    main()
