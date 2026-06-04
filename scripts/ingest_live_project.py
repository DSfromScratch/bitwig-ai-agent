"""
Liest das aktuell in Bitwig geöffnete Projekt live aus und speichert
Sound-Design-Rezepte als SoundRecipe-Nodes in Neo4j.

Voraussetzung:
  - Bitwig Studio läuft mit dem BitwigStepPlugin (Port 8002)
  - Das gewünschte Projekt ist geöffnet (z.B. "Chee - Hey Now")
  - Embedding-Server läuft (make embed-server)

Ausführen:
  python scripts/ingest_live_project.py
  python scripts/ingest_live_project.py --project "Chee - Hey Now"
  python scripts/ingest_live_project.py --dry-run
  python scripts/ingest_live_project.py --reset
  python scripts/ingest_live_project.py --no-params   # nur Track+Devices, keine Params
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Param-Interpretation ──────────────────────────────────────────────────────
# Gibt jedem 0–1 Float-Wert eine semantische Bedeutung

_PARAM_RANGES: dict[str, list[tuple[float, str]]] = {
    "filter cutoff":   [(0.2, "sehr dunkel"), (0.4, "dunkel/warm"), (0.6, "mittig"),
                        (0.8, "hell"), (1.0, "sehr hell/offen")],
    "resonance":       [(0.3, "neutral"), (0.6, "leicht betont"), (0.85, "stark betont"),
                        (1.0, "Selbstoszillation")],
    "attack":          [(0.05, "sehr schnell"), (0.15, "schnell"), (0.4, "mittel"),
                        (0.7, "langsam"), (1.0, "sehr langsam")],
    "decay":           [(0.15, "sehr kurz"), (0.3, "kurz"), (0.5, "mittel"),
                        (0.75, "lang"), (1.0, "sehr lang")],
    "sustain":         [(0.2, "fast keine Sustain"), (0.5, "halb"), (0.8, "hoch"),
                        (1.0, "voll")],
    "release":         [(0.1, "sofort"), (0.3, "kurz"), (0.6, "mittel"),
                        (0.9, "lang"), (1.0, "sehr lang")],
    "drive":           [(0.2, "clean"), (0.5, "leicht gesättigt"), (0.8, "gesättigt"),
                        (1.0, "stark verzerrt")],
    "mix":             [(0.2, "fast trocken"), (0.5, "50/50"), (0.8, "fast nass"),
                        (1.0, "komplett nass")],
    "wet":             [(0.2, "wenig"), (0.5, "mittel"), (0.8, "viel"), (1.0, "komplett nass")],
    "feedback":        [(0.2, "wenig"), (0.5, "mittel"), (0.75, "viel"), (1.0, "Selbstoszillation")],
    "depth":           [(0.2, "subtil"), (0.5, "deutlich"), (0.8, "intensiv"), (1.0, "maximal")],
    "rate":            [(0.2, "langsam"), (0.5, "mittel"), (0.8, "schnell"), (1.0, "sehr schnell")],
    "amount":          [(0.2, "wenig"), (0.5, "mittel"), (0.8, "stark"), (1.0, "maximal")],
    "volume":          [(0.3, "leise"), (0.6, "mittel"), (0.85, "laut"), (1.0, "voll")],
    "pan":             [(0.3, "links"), (0.45, "leicht links"), (0.55, "leicht rechts"),
                        (0.7, "rechts"), (0.5, "Mitte")],
    "threshold":       [(0.2, "sehr aggressiv"), (0.4, "aggressiv"), (0.6, "moderat"),
                        (0.8, "dezent"), (1.0, "inaktiv")],
    "ratio":           [(0.2, "sanft 2:1"), (0.4, "4:1"), (0.7, "8:1"), (1.0, "Limiter")],
    "pitch":           [(0.3, "tief gestimmt"), (0.5, "Standard"), (0.7, "hoch gestimmt")],
}


def _interpret_param(name: str, value: float) -> str:
    """Gibt eine kurze semantische Beschreibung für einen Parameterwert."""
    name_lower = name.lower()
    for key, ranges in _PARAM_RANGES.items():
        if key in name_lower:
            for threshold, label in sorted(ranges):
                if value <= threshold:
                    return f"{value:.3f} ({label})"
            return f"{value:.3f}"
    return f"{value:.3f}"


def _describe_device_chain(devices: list[str]) -> str:
    """Klassifiziert eine Device-Kette semantisch."""
    devs_lower = [d.lower() for d in devices]
    if not devices:
        return "kein Instrument"
    instrument = devices[0]
    fx = devices[1:] if len(devices) > 1 else []

    parts = [f"Instrument: {instrument}"]
    if fx:
        parts.append(f"FX-Kette: {' → '.join(fx)}")
    return " | ".join(parts)


def _classify_track_role(track_name: str, devices: list[str]) -> str:
    """Bestimmt die Rolle des Tracks (Kick, Bass, Lead, Pad, etc.)."""
    name_lower = track_name.lower()
    devs_lower = " ".join(d.lower() for d in devices)

    if any(k in name_lower for k in ["kick", "bd", "bass drum"]):
        return "Kick"
    if any(k in name_lower for k in ["snare", "clap", "rimshot", "rim", "snr"]):
        return "Snare/Clap"
    if any(k in name_lower for k in ["hat", "hh", "cymbal", "crash", "ride", "perc"]):
        return "Hi-Hat/Percussion"
    if any(k in name_lower for k in ["bass", "sub", "808"]):
        return "Bass"
    if any(k in name_lower for k in ["vox", "vocal", "voice", "sing"]):
        return "Vocals"
    if any(k in name_lower for k in ["lead", "solo", "melody", "melo"]):
        return "Lead"
    if any(k in name_lower for k in ["pad", "strings", "atmo", "ambient", "texture", "sweep"]):
        return "Pad/Atmosphere"
    if any(k in name_lower for k in ["chord", "keys", "piano", "pluck", "stab"]):
        return "Chords/Keys"
    if any(k in name_lower for k in ["fx", "effect", "riser", "impact"]):
        return "FX"
    if "drum" in devs_lower or "e-kit" in devs_lower:
        return "Drums"
    return "Sonstiges"


def _build_recipe(project_name: str, track: dict, params: dict) -> dict:
    """Erstellt ein vollständiges Sound-Rezept aus Track- und Param-Daten."""
    track_name = track.get("name", "Unbekannt")
    devices    = track.get("devices", [])
    idx        = track.get("idx", 0)
    role       = _classify_track_role(track_name, devices)
    device_str = _describe_device_chain(devices)

    # Parameterbeschreibung
    param_parts: list[str] = []
    for p in params.get("params", []):
        pname = p.get("name", "")
        pval  = p.get("value", 0.0)
        if pname and pname.lower() not in ("", "—", "-", "unnamed"):
            param_parts.append(f"{pname}: {_interpret_param(pname, pval)}")

    # Lernbarer Inhalt für RAG
    content_lines = [
        f"**Sound-Rezept: {track_name}** [{role}] — {project_name}",
        f"Device-Kette: {device_str}",
    ]
    if param_parts:
        content_lines.append("Remote-Control-Parameter:")
        content_lines.extend(f"  • {p}" for p in param_parts)

    primary_device = params.get("device") or (devices[0] if devices else "")
    recipe_id = f"{project_name.lower().replace(' ', '_').replace('-', '_')}__track{idx}__{track_name.lower().replace(' ', '_')}"

    return {
        "id":           recipe_id,
        "track_name":   track_name,
        "track_index":  idx,
        "role":         role,
        "project":      project_name,
        "devices":      devices,
        "primary_device": primary_device,
        "device_chain": device_str,
        "params":       params.get("params", []),
        "param_summary": " | ".join(param_parts[:5]),
        "content":      "\n".join(content_lines),
        "source":       f"SoundRecipe:{recipe_id}",
    }


# ── Neo4j Storage ─────────────────────────────────────────────────────────────

def _store_recipes(recipes: list[dict], project_name: str) -> int:
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    print(f"\n[embed] Lade Embedding-Modell …")
    emb_model = get_embeddings()
    dim = len(emb_model.embed_query("test"))
    print(f"[embed] Bereit — Dimension: {dim}")

    stored = 0
    t0 = time.time()
    with neo4j_session() as s:
        for r in recipes:
            vec = emb_model.embed_documents([r["content"]])[0]
            s.run("""
                MERGE (n:SoundRecipe {recipe_id: $id})
                SET n.track_name    = $track_name,
                    n.track_index   = $track_index,
                    n.role          = $role,
                    n.project       = $project,
                    n.devices       = $devices,
                    n.primary_device= $primary_device,
                    n.device_chain  = $device_chain,
                    n.param_summary = $param_summary,
                    n.content       = $content,
                    n.source        = $source,
                    n.embedding     = $embedding
            """,
            id=r["id"],
            track_name=r["track_name"],
            track_index=r["track_index"],
            role=r["role"],
            project=r["project"],
            devices=r["devices"],
            primary_device=r["primary_device"],
            device_chain=r["device_chain"],
            param_summary=r["param_summary"],
            content=r["content"],
            source=r["source"],
            embedding=vec,
            )
            # MADE_FROM-Kante zum ProjectionPattern wenn vorhanden
            if r["role"] in ("Kick", "Snare/Clap", "Bass"):
                s.run("""
                    MATCH (pp:ProductionPattern)
                    WHERE pp.source_project CONTAINS $project AND pp.name CONTAINS $role
                    MATCH (sr:SoundRecipe {recipe_id: $id})
                    MERGE (sr)-[:DERIVED_FROM]->(pp)
                """, project=r["project"], role=r["role"], id=r["id"])
            stored += 1
        print(f"  {stored} SoundRecipe-Nodes gespeichert ({time.time()-t0:.1f}s)")

    # HNSW-Index für SoundRecipe anlegen falls nicht vorhanden
    with neo4j_session() as s:
        try:
            s.run("""
                CREATE VECTOR INDEX sound_recipe_embedding IF NOT EXISTS
                FOR (n:SoundRecipe) ON n.embedding
                OPTIONS {indexConfig: {`vector.dimensions`: $dim,
                                       `vector.similarity_function`: 'cosine'}}
            """, dim=dim)
            print("  VECTOR INDEX sound_recipe_embedding angelegt/bestätigt")
        except Exception as e:
            print(f"  Index-Hinweis: {e}")

    return stored


# ── Main ──────────────────────────────────────────────────────────────────────

_DRY_RUN_DEMO = {
    "tracks": [
        {"idx": 1, "name": "Kick",         "devices": ["Poly Grid", "Saturator", "Compressor"]},
        {"idx": 2, "name": "Snare",        "devices": ["Poly Grid", "Reverb"]},
        {"idx": 3, "name": "SUBMOTION-Low","devices": ["Poly Grid", "Compressor", "EQ-5"]},
        {"idx": 4, "name": "Stringer",     "devices": ["Sampler", "Chorus+", "Reverb"]},
        {"idx": 5, "name": "Sine Pluck 1", "devices": ["Polysynth", "Delay-2"]},
    ],
    "tempo": 130.0, "total": 5,
}

_DRY_RUN_PARAMS = {
    "device": "Poly Grid",
    "params": [
        {"name": "Filter Cutoff", "value": 0.34},
        {"name": "Resonance",     "value": 0.22},
        {"name": "Attack",        "value": 0.02},
        {"name": "Decay",         "value": 0.18},
        {"name": "Drive",         "value": 0.55},
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bitwig Live-Projekt → Neo4j SoundRecipes")
    parser.add_argument("--project",   default="", help="Projekt-Name (nur für Metadaten)")
    parser.add_argument("--dry-run",   action="store_true",
                        help="Zeigt Beispiel-Output ohne Bitwig-Verbindung")
    parser.add_argument("--reset",     action="store_true", help="Bestehende SoundRecipes löschen")
    parser.add_argument("--no-params", action="store_true", help="Keine Param-Abfrage pro Track")
    parser.add_argument("--timeout",   type=float, default=4.0, help="OSC-Timeout pro Anfrage")
    args = parser.parse_args()

    project_name = args.project or "Unbekanntes Projekt"

    # Dry-Run: funktioniert ohne Bitwig (Demo-Daten)
    if args.dry_run:
        print(f"[dry-run] Simulierter Scan — kein Bitwig nötig")
        print(f"[dry-run] Projekt: {project_name or 'Demo'} | Tempo: {_DRY_RUN_DEMO['tempo']:.1f} BPM")
        print(f"[dry-run] {_DRY_RUN_DEMO['total']} Demo-Tracks:\n")
        recipes = []
        for track in _DRY_RUN_DEMO["tracks"]:
            params = {**_DRY_RUN_PARAMS, "track": track["idx"]}
            recipe = _build_recipe(project_name or "Demo-Projekt", track, params)
            recipes.append(recipe)
            print(f"  Track {track['idx']:>2}: {track['name']:<25} [{recipe['role']}]")
            print(f"           Devices: {', '.join(track['devices'])}")
        print(f"\n[dry-run] Beispiel-Rezept:\n{'─'*60}")
        print(recipes[0]["content"])
        print(f"\n{'─'*60}")
        print(f"[dry-run] So würden {len(recipes)} SoundRecipe-Nodes in Neo4j geschrieben.")
        print("\nVoraussetzungen für echten Scan:")
        print("  1. Bitwig Studio starten")
        print("  2. 'Chee - Hey Now' öffnen")
        print("  3. Settings → Controller → BitwigStepPlugin → Reload Extension")
        print("  4. make embed-server")
        print(f"  5. make ingest-project PROJECT=\"{project_name or 'Chee - Hey Now'}\"")
        return

    # Verbindung prüfen via Step-Plugin Port 8002 (Port 8001 auf Mac nicht aktiv)
    from src.agent.osc.project_scan import scan_project as _ping_scan
    _ping = _ping_scan(timeout=2.0)
    if not _ping.get("tracks") and not _ping.get("_raw"):
        print("❌  Bitwig nicht erreichbar (Port 8002).")
        print("\nCheckliste:")
        print("  1. Bitwig Studio starten + Projekt öffnen")
        print("  2. Settings → Controller → BitwigStepPlugin aktiv?")
        print("  3. Nach Extension-Update: Bitwig neu starten")
        sys.exit(1)
    print("✅  Bitwig verbunden")

    # Projekt scannen
    print("\n[scan] Lese Projekt-Struktur …")
    from src.agent.osc.project_scan import scan_project, query_track_params
    project_data = scan_project(timeout=args.timeout)

    tracks = project_data.get("tracks", [])
    tempo  = project_data.get("tempo", 0.0)
    total  = project_data.get("total", 0)

    if not tracks:
        print("❌  Keine Tracks gefunden — Projekt geöffnet?")
        if project_data.get("_raw"):
            print(f"   Raw-Response: {project_data['_raw'][:200]}")
        sys.exit(1)

    print(f"[scan] {total} Tracks | Tempo: {tempo:.1f} BPM | Projekt: {project_name}")
    print()

    # Tracks + Params abfragen
    recipes: list[dict] = []
    for track in tracks:
        idx  = track.get("idx", 0)
        name = track.get("name", f"Track {idx}")
        devs = track.get("devices", [])
        print(f"  Track {idx:>2}: {name:<30} Devices: {', '.join(devs) or '–'}", end="")

        params: dict = {"track": idx, "device": devs[0] if devs else "", "params": []}
        if not args.no_params and devs:
            params = query_track_params(idx, timeout=args.timeout)
            param_count = len([p for p in params.get("params", [])
                               if p.get("name") and p["name"] not in ("", "—", "-")])
            print(f" → {param_count} Params")
        else:
            print()

        recipe = _build_recipe(project_name, track, params)
        recipes.append(recipe)

    print(f"\n[summary] {len(recipes)} Sound-Rezepte gesammelt")

    if args.dry_run:
        print("\n[dry-run] Erste 3 Rezepte:")
        for r in recipes[:3]:
            print(f"\n{'─'*60}")
            print(r["content"][:400])
        return

    if args.reset:
        from src.knowledge.neo4j_graph import session as neo4j_session
        with neo4j_session() as s:
            result = s.run("""
                MATCH (n:SoundRecipe) WHERE n.project = $p
                DELETE n RETURN count(n) AS c
            """, p=project_name).single()
            print(f"[reset] {result['c']} bestehende SoundRecipes gelöscht")

    stored = _store_recipes(recipes, project_name)
    print(f"\n✅  {stored} SoundRecipes in Neo4j gespeichert")
    print("Durchsuchbar via query_bitwig_docs (Vektorsuche über SoundRecipe-Nodes)")


if __name__ == "__main__":
    main()
