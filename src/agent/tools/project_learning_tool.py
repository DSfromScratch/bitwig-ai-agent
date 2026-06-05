"""
Tool: scan_and_learn_project

Lässt den Agenten das aktuell in Bitwig geöffnete Projekt selbst analysieren
und in der Wissensdatenbank speichern — Tracks, Devices, Parameter-Seiten,
Audio-Samples und (wenn ANTHROPIC_API_KEY gesetzt) Grid-Visual-Analyse.

Der Agent ruft dieses Tool auf wenn:
- Er ein unbekanntes Projekt vorfindet
- Gefragt wird "Was ist gerade in Bitwig offen?"
- Er Sound-Design-Details eines Projekts verstehen möchte
- query_bitwig_docs keine ausreichenden Infos liefert
"""
from __future__ import annotations

import os
import time
from langchain_core.tools import tool


@tool
def scan_and_learn_project(project_name: str = "") -> str:
    """Scannt das aktuell in Bitwig geöffnete Projekt und lernt daraus.

    Analysiert alle Tracks mit ihren Devices und Parametern, erkennt
    Grid-Patches (Poly Grid / FX Grid), analysiert sie visuell mit
    Claude Vision und speichert alles in der Wissensdatenbank.

    Nach dem Aufruf kann query_bitwig_docs detaillierte Fragen über
    das Projekt beantworten (Sound-Design, Geräte-Einstellungen, etc.)

    Args:
        project_name: Name des Projekts (z.B. "Chee - Hey Now").
                      Leer lassen wenn unbekannt — wird aus Bitwig gelesen.
    """
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(ROOT))

    lines: list[str] = []

    # ── 1. Vollständiger Snapshot via neuem Endpoint ──────────────────────
    from src.agent.osc.project_scan import query_project_snapshot, query_track_params_all, open_track_device

    if not project_name:
        from src.agent.osc.project_scan import get_project_name
        project_name = get_project_name() or "Aktuelles Projekt"

    try:
        snapshot = query_project_snapshot(project_name, timeout=8.0)
    except RuntimeError:
        return "❌ Bitwig nicht erreichbar. Bitte Bitwig starten und Projekt öffnen."

    tracks = [{"idx": t.idx, "name": t.name, "devices": t.devices} for t in snapshot.tracks]
    tempo  = snapshot.tempo
    total  = len(tracks)
    scene_names = [s.name for s in snapshot.scenes]

    lines.append(f"📂 Projekt: **{project_name}** | {total} Tracks | {tempo:.0f} BPM")
    if scene_names:
        lines.append(f"   Szenen: {', '.join(scene_names)}")
    if snapshot.timeline:
        tl = [(s.name, int(s.bar)) for s in snapshot.timeline]
        lines.append(f"   Timeline: {tl}")

    # Snapshot + Scene-Nodes in Neo4j
    try:
        from src.knowledge.repositories import ProjectSnapshotRepository
        ProjectSnapshotRepository().save(snapshot)
    except Exception:
        pass

    # ── 2. Tracks + Parameter scannen ────────────────────────────────────
    from scripts.ingest_live_project import _build_recipe, _store_recipes

    recipes: list[dict] = []
    grid_tracks: list[dict] = []
    _GRID_DEVICES = {"poly grid", "fx grid", "note grid"}

    lines.append("\n**Track-Analyse:**")
    for track in tracks:
        idx  = track.get("idx", 0)
        name = track.get("name", f"Track {idx}")
        devs = track.get("devices", [])

        params: dict = {"track": idx, "device": devs[0] if devs else "", "params": [], "pages": []}
        if devs:
            params = query_track_params_all(idx, timeout=10.0)

        recipe = _build_recipe(project_name, track, params)
        recipes.append(recipe)

        page_count = len(params.get("pages", []))
        lines.append(f"  Track {idx:>2}: {name:<25} → {', '.join(devs[:3]) or '–'}"
                     + (f" ({page_count} Seiten)" if page_count > 1 else ""))

        if any(d.lower() in _GRID_DEVICES for d in devs):
            grid_tracks.append(recipe)

    # ── 3. SoundRecipes speichern ─────────────────────────────────────────
    try:
        stored = _store_recipes(recipes, project_name)
        lines.append(f"\n✅ {stored} SoundRecipe-Nodes in Wissensdatenbank gespeichert")
    except Exception as e:
        lines.append(f"\n⚠️ Embedding-Server nicht verfügbar: {e}")
        lines.append("   Starte make embed-server und wiederhole den Scan.")
        return "\n".join(lines)

    # ── 3b. ProjectTemplate aus Snapshot + Recipes ───────────────────────
    try:
        from src.agent.models.project_template import ProjectTemplate
        from src.knowledge.repositories import ProjectTemplateRepository
        tmpl = ProjectTemplate.from_snapshot(snapshot)
        ProjectTemplateRepository().save(tmpl)
        lines.append(f"   📋 ProjectTemplate '{project_name}' in Neo4j gespeichert")
    except Exception:
        pass

    # ── 4. Audio-Samples analysieren (falls vorhanden) ───────────────────
    from pathlib import Path
    PROJECTS_DIR = Path("/home/sija/Bitwig Studio/Projects")
    samples_dir  = PROJECTS_DIR / project_name / "samples"
    if samples_dir.exists():
        wav_files = list(samples_dir.glob("*.wav"))
        if wav_files:
            lines.append(f"\n🎵 {len(wav_files)} Audio-Samples gefunden — analysiere …")
            try:
                from scripts.ingest_audio_samples import analyze_file, store_samples, _build_content
                features = []
                for wav in wav_files[:20]:   # max 20 für Performance
                    feat = analyze_file(wav, max_duration=15.0)
                    if feat:
                        feat["project"] = project_name
                        features.append(feat)
                if features:
                    stored_audio = store_samples(features, project_name)
                    lines.append(f"   ✅ {stored_audio} AudioSample-Nodes gespeichert")
            except Exception as e:
                lines.append(f"   ⚠️ Audio-Analyse fehlgeschlagen: {e}")

    # ── 5. Grid-Visual-Analyse (wenn ANTHROPIC_API_KEY vorhanden) ────────
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key and grid_tracks:
        lines.append(f"\n🔬 Grid-Visual-Analyse für {len(grid_tracks)} Poly/FX-Grid-Tracks:")
        try:
            from scripts.analyze_grid_screenshot import (
                fetch_screenshot, analyze_with_claude, store_analysis
            )

            for recipe in grid_tracks:
                tidx   = recipe["track_index"]
                tname  = recipe["track_name"]
                device = recipe["primary_device"]

                lines.append(f"  → Track {tidx}: {tname} ({device}) …")

                # Grid-Editor öffnen
                opened = open_track_device(tidx, timeout=3.0)
                if not opened:
                    lines.append(f"    ⚠️ Konnte Fenster nicht öffnen")
                    continue

                time.sleep(1.5)  # UI rendern lassen

                # Screenshot + Analyse
                img = fetch_screenshot(timeout=12.0)
                if not img:
                    lines.append(f"    ⚠️ VNC-Screenshot fehlgeschlagen")
                    continue

                analysis = analyze_with_claude(img, track_name=tname, device_name=opened)
                if analysis:
                    store_analysis(tidx, tname, opened, analysis, project_name)
                    # Erste Zeile der Analyse als Vorschau
                    preview = analysis.split("\n")[0][:100]
                    lines.append(f"    ✅ {preview}")
                else:
                    lines.append(f"    ⚠️ Claude Vision Analyse fehlgeschlagen")

                time.sleep(0.3)

        except Exception as e:
            lines.append(f"   ⚠️ Grid-Analyse Fehler: {e}")

    elif grid_tracks and not anthropic_key:
        lines.append(f"\nℹ️  {len(grid_tracks)} Grid-Tracks erkannt.")
        lines.append("   Für visuelle Grid-Analyse: ANTHROPIC_API_KEY in .env setzen")

    # ── 6. Zusammenfassung ────────────────────────────────────────────────
    lines.append(f"\n📚 Wissensdatenbank aktualisiert. query_bitwig_docs kennt jetzt:")
    lines.append(f"   • {len(recipes)} Sound-Rezepte mit Parameter-Details (params_json)")
    if grid_tracks and anthropic_key:
        lines.append(f"   • {len(grid_tracks)} Grid-Patch-Analysen (Signal-Flow, Module)")
    lines.append(f"   • Alle {total} Track-Konfigurationen aus '{project_name}'")
    lines.append(f"   • ProjectSnapshot + Template → reconstruct_project kann Projekt neu erstellen")

    return "\n".join(lines)
