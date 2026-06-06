#!/usr/bin/env python3
"""
Batch-Scan aller BitwigTracks-Projekte für Trainings-Daten.

Ablauf pro Projekt:
  1. Öffnet das Projekt in Bitwig via AppleScript (open-Befehl auf Mac)
  2. Wartet bis Bitwig bereit ist (OSC-Ping)
  3. Führt scan_and_learn_project + ingest_midi_clips aus
  4. Weiter mit nächstem Projekt

Aufruf:
  python scripts/batch_scan_projects.py
  python scripts/batch_scan_projects.py --only Sequence1 Sequence2 Drum1
  python scripts/batch_scan_projects.py --skip NoteGrid1 NoteGrid2
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Repo-Root zum Python-Pfad hinzufügen
sys.path.insert(0, str(Path(__file__).parent.parent))

# Projekte die wenig MIDI-Inhalt haben (nur Grid-Patches, keine Noten)
# werden trotzdem gescannt aber ohne MIDI-Ingest
MIDI_SKIP = {
    "NoteGrid1", "NoteGrid2", "NoteGrid3", "NoteGrid4", "NoteGrid5",
    "NoteGrid6", "NoteGrid7", "NoteGrid8", "NoteGrid9", "NoteGrid10",
    "NoteGrid11", "NoteGrid12", "NoteGrid13", "NoteGrid14", "NoteGrid15",
    "NoteGrid16", "NoteGrid17", "NoteGrid18", "NoteGrid19", "NoteGrid20",
    "NoteGrid21",
}

MAC_PROJECTS_DIR = "/Users/sija/Documents/Bitwig Studio/Projects/BitwigTracks"
MAC_HOST = "sija@192.168.0.4"
MAC_BITWIG = "/Applications/Bitwig Studio.app/Contents/MacOS/BitwigStudio"

BOOT_WAIT = 28      # Sekunden bis Bitwig nach open() bereit ist (Projekte mit Samples brauchen länger)
OSC_TIMEOUT = 8.0   # Sekunden für OSC-Ping


def close_current_project_on_mac() -> None:
    """Schließt das aktuelle Bitwig-Projekt (Cmd+W), bestätigt 'Don't Save' via Cmd+D."""
    # Cmd+W — Projekt schließen
    subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", MAC_HOST,
         "osascript -e 'tell application \"System Events\" to tell process \"Bitwig Studio\" to keystroke \"w\" using {command down}'"],
        capture_output=True, timeout=15,
    )
    time.sleep(2.0)
    # Cmd+D — "Don't Save" bestätigen (falls Dialog erscheint)
    subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", MAC_HOST,
         "osascript -e 'tell application \"System Events\" to tell process \"Bitwig Studio\" to keystroke \"d\" using {command down}'"],
        capture_output=True, timeout=10,
    )
    time.sleep(1.5)


def open_project_on_mac(project_name: str) -> bool:
    """Schließt das aktuelle Projekt, dann öffnet das nächste in Bitwig."""
    close_current_project_on_mac()
    path = f"{MAC_PROJECTS_DIR}/{project_name}.bwproject"
    cmd = f"open -a 'Bitwig Studio' '{path}'"
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", MAC_HOST, cmd],
        capture_output=True, timeout=15,
    )
    return result.returncode == 0


def activate_mix_mode_and_show_all_tracks() -> None:
    """Wechselt in Bitwig zum Mix-Modus und blendet alle Tracks ein (AppleScript)."""
    applescript = """
    tell application "Bitwig Studio" to activate
    delay 1.5
    tell application "System Events"
        tell process "Bitwig Studio"
            -- Mix-Modus: Klick auf Mix-Tab (Tastenkürzel M oder Button)
            keystroke "m" using {command down}
            delay 0.5
            -- Alle Tracks einblenden: Rechtsklick-Menü im Mixer → Show All Tracks
            -- Alternative: Cmd+A wählt alle, dann einblenden
            keystroke "a" using {command down}
            delay 0.3
        end tell
    end tell
    """
    subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", MAC_HOST,
         f"osascript -e '{applescript}'"],
        capture_output=True, timeout=10,
    )


def wait_for_bitwig(expected_project: str, timeout: float = 40.0) -> bool:
    """Wartet bis Bitwig das richtige Projekt geladen hat (Projektname reicht)."""
    from src.agent.osc.project_scan import get_project_name
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            name = get_project_name(timeout=2.0)
            if name and expected_project.lower() in name.lower():
                time.sleep(3)   # kurze Extra-Pause für vollständiges Laden
                return True
        except Exception:
            pass
        time.sleep(3)
    return False


def scan_project(project_name: str, do_midi: bool) -> dict:
    """Führt den vollständigen Scan-Pipeline durch."""
    from src.agent.osc.project_scan import get_project_name, scan_project as osc_scan
    from src.agent.tools.project_learning_tool import scan_and_learn_project

    result = {"project": project_name, "midi": False, "learned": False, "error": None}

    try:
        # 1. Projekt-Scan + Neo4j
        print(f"    scan_and_learn_project({project_name})...")
        out = scan_and_learn_project.invoke({"project_name": project_name})
        result["learned"] = "gespeichert" in out.lower() or "ok" in out.lower() or len(out) > 10
        print(f"    → {out[:120]}")
    except Exception as e:
        result["error"] = f"scan: {e}"
        print(f"    ⚠️ scan_and_learn_project: {e}")

    if do_midi:
        try:
            # 2. MIDI-Ingest — via subprocess mit --project Argument
            print(f"    ingest_midi_clips({project_name})...")
            proc = subprocess.run(
                [sys.executable, "scripts/ingest_midi_clips.py",
                 "--project", project_name],
                capture_output=False, timeout=120,
            )
            result["midi"] = proc.returncode == 0
            if proc.returncode != 0:
                result["error"] = (result.get("error") or "") + " midi: non-zero exit"
        except Exception as e:
            result["error"] = (result.get("error") or "") + f" midi: {e}"
            print(f"    ⚠️ ingest_midi_clips: {e}")

    return result


def main():
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Batch-Scan Bitwig-Projekte")
    parser.add_argument("--only", nargs="+", help="Nur diese Projekte scannen")
    parser.add_argument("--skip", nargs="+", help="Diese Projekte überspringen")
    parser.add_argument("--no-open", action="store_true",
                        help="Bitwig nicht automatisch öffnen (Projekt schon offen)")
    args = parser.parse_args()

    # Projektliste
    projects_dir = Path("BitwigTracks")
    all_projects = sorted(p.stem for p in projects_dir.glob("*.bwproject"))

    if args.only:
        projects = [p for p in all_projects if p in args.only]
    elif args.skip:
        projects = [p for p in all_projects if p not in args.skip]
    else:
        projects = all_projects

    # Schon gescannte überspringen
    from src.knowledge.neo4j_graph import session, is_available
    already_done = set()
    if is_available():
        with session() as s:
            rows = s.run("MATCH (p:BitwigProject) RETURN p.name").data()
            already_done = {r["p.name"] for r in rows}

    todo = [p for p in projects if p not in already_done]
    skip_done = [p for p in projects if p in already_done]

    if skip_done:
        print(f"Bereits in Neo4j (überspringe): {', '.join(skip_done)}")

    print(f"\n{'─'*55}")
    print(f"Zu scannen: {len(todo)} Projekte")
    print(f"{'─'*55}\n")

    results = []
    for i, project_name in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {project_name}")

        if not args.no_open:
            print(f"  → Öffne in Bitwig...")
            if not open_project_on_mac(project_name):
                print(f"  ⚠️ open fehlgeschlagen — überspringe")
                continue
            print(f"  → Warte bis Bitwig Projekt+Tracks geladen hat...")
            time.sleep(BOOT_WAIT)
            if not wait_for_bitwig(expected_project=project_name, timeout=40):
                print(f"  ⚠️ Bitwig hat {project_name} nicht geladen — überspringe")
                continue
            print(f"  → Mix-Modus + alle Tracks einblenden...")
            activate_mix_mode_and_show_all_tracks()
            time.sleep(1.5)
        else:
            print(f"  → Verwende aktuell geöffnetes Projekt")

        do_midi = project_name not in MIDI_SKIP
        res = scan_project(project_name, do_midi=do_midi)
        results.append(res)

        status = "✓" if not res["error"] else "⚠"
        midi_str = "(+MIDI)" if res["midi"] else ""
        print(f"  {status} {project_name} {midi_str}\n")

    # Zusammenfassung
    print(f"\n{'─'*55}")
    print(f"Abgeschlossen: {len(results)}/{len(todo)} Projekte")
    ok = sum(1 for r in results if not r["error"])
    print(f"  ✓ Erfolgreich: {ok}")
    print(f"  ⚠ Fehler:      {len(results) - ok}")

    # Context-Pairs generieren
    if ok > 0:
        print(f"\nGeneriere Context-Pairs...")
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "gen_ctx", Path("scripts/generate_context_pairs.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            print("✓ Context-Pairs aktualisiert")
        except Exception as e:
            print(f"  Context-Pairs: {e}")
            print(f"  Manuell: python scripts/generate_context_pairs.py")


if __name__ == "__main__":
    main()
