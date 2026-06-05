"""
Interaktiver Arranger-Track-Ingest für Bitwig-Projekte die Timeline-basiert sind.

Ablauf:
  1. Projekt in Bitwig öffnen
  2. Skript starten: python scripts/ingest_arranger_tracks.py --project "BitStep"
  3. Einen Track im Arranger anklicken → Enter drücken
  4. Optional: Playhead auf MIDI-Clip positionieren → Enter für Noten
  5. Weiter mit nächstem Track, 's' = Skip, 'q' = Fertig

Voraussetzung: Embedding-Server läuft (make embed-server)
"""
from __future__ import annotations
import argparse
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.agent.osc.project_scan import query_cursor_track, query_arranger_clip_notes, get_project_name


def _classify_role(track_name: str, devices: list[str]) -> str:
    name = track_name.lower()
    dev  = " ".join(d.lower() for d in devices)
    if any(k in name for k in ("kick", "bass drum", "bd")):         return "Kick"
    if any(k in name for k in ("snare", "clap", "rimshot")):        return "Snare/Clap"
    if any(k in name for k in ("hat", "perc", "cymbal")):           return "Hi-Hat/Perc"
    if any(k in name for k in ("drum",)):                           return "Drums"
    if any(k in name for k in ("bass",)):                           return "Bass"
    if any(k in name for k in ("arp", "stringer")):                 return "Arp"
    if any(k in name for k in ("pad", "ambient", "texture", "atmo", "loopy", "swarm")): return "Pad"
    if any(k in name for k in ("lead", "melody", "pluck", "sine", "sawtooth")): return "Lead"
    if any(k in name for k in ("chord", "stab", "keys", "piano")):  return "Chords/Keys"
    if any(k in name for k in ("vox", "vocal", "voice")):           return "Vocals"
    if any(k in name for k in ("fx", "effect", "noise")):           return "FX"
    if "poly grid" in dev or "fx grid" in dev:                      return "Synth"
    return "Synth"


def _describe_device_chain(devices: list[str]) -> str:
    if not devices:
        return "kein Instrument"
    return " → ".join(devices[:4])


def _build_recipe(project_name: str, track_name: str, devices: list[str],
                  notes: list[dict] | None = None) -> dict:
    role           = _classify_role(track_name, devices)
    primary_device = devices[0] if devices else ""
    device_chain   = _describe_device_chain(devices)
    track_idx      = int(time.time() * 1000) % 10000  # unique-ish idx

    notes_json = None
    if notes:
        notes_json = str(notes[:32])

    recipe_id = f"__track{track_idx}__{track_name.lower().replace(' ', '_').replace('/', '_')}"

    content_lines = [
        f"**Sound-Rezept: {track_name}** [{role}] — {project_name}",
        f"Gerät: {device_chain}",
        f"Rolle: {role}",
    ]
    if notes:
        content_lines.append(f"MIDI-Noten: {len(notes)} Noten")

    return {
        "recipe_id":     recipe_id,
        "track_name":    track_name,
        "role":          role,
        "project":       project_name,
        "track_index":   track_idx,
        "device_chain":  device_chain,
        "primary_device": primary_device,
        "notes_json":    notes_json,
        "content":       "\n".join(content_lines),
        "source":        f"SoundRecipe:{recipe_id}",
    }


def _store_recipes(recipes: list[dict], project_name: str) -> int:
    from src.knowledge.store import get_embeddings
    from src.knowledge.neo4j_graph import session

    print(f"\n[embed] Lade Embedding-Modell …")
    emb_model = get_embeddings()
    dim = len(emb_model.embed_query("test"))
    print(f"[embed] Bereit — Dimension: {dim}")

    t0 = time.time()
    stored = 0
    with session() as s:
        for r in recipes:
            vec = emb_model.embed_documents([r["content"]])[0]
            s.run("""
                MERGE (n:SoundRecipe {recipe_id: $id})
                SET n.track_name     = $track_name,
                    n.role           = $role,
                    n.project        = $project,
                    n.track_index    = $track_index,
                    n.device_chain   = $device_chain,
                    n.primary_device = $primary_device,
                    n.notes_json     = $notes_json,
                    n.content        = $content,
                    n.source         = $source,
                    n.embedding      = $embedding
            """,
                id=r["recipe_id"], track_name=r["track_name"], role=r["role"],
                project=r["project"], track_index=r["track_index"],
                device_chain=r["device_chain"], primary_device=r["primary_device"],
                notes_json=r["notes_json"], content=r["content"],
                source=r["source"], embedding=vec,
            )

            # BitwigProject-Node anlegen
            s.run("""
                MERGE (p:BitwigProject {name: $name})
                SET p.tempo = 0
            """, name=project_name)

            stored += 1

        # HNSW-Vektorindex anlegen
        try:
            s.run(f"""
                CREATE VECTOR INDEX sound_recipe_embedding IF NOT EXISTS
                FOR (n:SoundRecipe) ON n.embedding
                OPTIONS {{indexConfig: {{`vector.dimensions`: {dim},
                                         `vector.similarity_function`: 'cosine'}}}}
            """)
            print(f"  VECTOR INDEX sound_recipe_embedding angelegt/bestätigt")
        except Exception:
            pass

    print(f"  {stored} SoundRecipe-Nodes gespeichert ({time.time()-t0:.1f}s)")
    return stored


def main() -> None:
    parser = argparse.ArgumentParser(description="Interaktiver Arranger-Track-Ingest")
    parser.add_argument("--project", "-p", default="",
                        help="Projektname (leer = auto aus Bitwig)")
    parser.add_argument("--no-notes", action="store_true",
                        help="MIDI-Noten nicht abfragen")
    args = parser.parse_args()

    # Projektname aus Bitwig holen wenn nicht angegeben
    project_name = args.project.strip()
    if not project_name:
        project_name = get_project_name() or "Unbekanntes Projekt"
    print(f"\n{'='*55}")
    print(f"  Arranger-Ingest: {project_name}")
    print(f"{'='*55}")
    print("  Klicke einen Track in Bitwig an → Enter")
    print("  s = überspringen | q = fertig & speichern")
    print()

    recipes: list[dict] = []
    seen_names: set[str] = set()

    while True:
        raw = input("  [Enter] Track gelesen, [s] skip, [q] fertig: ").strip().lower()
        if raw == "q":
            break
        if raw == "s":
            print("  ⏭  übersprungen")
            continue

        # Cursor-Track Info lesen
        info = query_cursor_track()
        name = info.get("name", "").strip()
        devices = info.get("devices", [])
        is_group = info.get("is_group", False)

        if not name:
            print("  ⚠  Kein Track ausgewählt oder keine Verbindung zu Bitwig")
            continue
        if is_group:
            print(f"  ⏭  '{name}' ist ein Group-Track — übersprungen")
            continue
        if name in seen_names:
            print(f"  ⏭  '{name}' bereits erfasst")
            continue

        seen_names.add(name)
        print(f"  ✓  Track: {name}  |  Devices: {devices or ['–']}")

        # MIDI-Noten abfragen
        notes = None
        if not args.no_notes:
            note_raw = input("     Playhead auf MIDI-Clip? [Enter] = ja, [n] = nein: ").strip().lower()
            if note_raw != "n":
                clip = query_arranger_clip_notes()
                notes = clip.get("notes", [])
                beats = clip.get("loop_beats", 0)
                if notes:
                    print(f"     🎵 {len(notes)} Noten, {beats:.1f} Beats")
                else:
                    print(f"     (keine Noten gefunden)")

        recipe = _build_recipe(project_name, name, devices, notes)
        recipes.append(recipe)
        print(f"  📋 Rezept erstellt ({len(recipes)} gesamt)\n")

    if not recipes:
        print("\n⚠  Keine Tracks erfasst.")
        return

    print(f"\n{'='*55}")
    print(f"  Speichere {len(recipes)} SoundRecipes für '{project_name}' …")
    print(f"{'='*55}")
    stored = _store_recipes(recipes, project_name)
    print(f"\n✅  {stored} SoundRecipes in Neo4j gespeichert")
    print(f"Durchsuchbar via query_bitwig_docs (Vektorsuche über alle Nodes)\n")


if __name__ == "__main__":
    main()
