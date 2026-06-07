"""
Liest MIDI-Clip-Noten aus Bitwig und analysiert:
  - Tonart (Key) aus Pitch-Verteilung
  - Akkorde (Gleichzeitige Noten)
  - Rhythmus-Pattern (Step-Positionen)
  - Melodie-Kontur (Pitch-Bewegung)

Speichert MidiClip-Nodes in Neo4j + verbessert SoundRecipe-Key-Felder.

Voraussetzung: Bitwig läuft + Extension aktiv

Ausführen:
  python scripts/ingest_midi_clips.py --project "Chee - Hey Now"
  python scripts/ingest_midi_clips.py --track 10   # nur ein Track
  python scripts/ingest_midi_clips.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NOTE_NAMES  = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
STEP_BEATS  = 0.25   # Bitwig Standard: 1 Step = 1/16 Note = 0.25 Beats

# Dur/Moll-Schablonen (Chroma-Profil Krumhansl-Schmuckler)
_MAJOR = [6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88]
_MINOR = [6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17]


# ── Musikalische Analyse ──────────────────────────────────────────────────────

def detect_key(notes: list[dict]) -> dict:
    """Krumhansl-Schmuckler Key-Finding aus Pitch-Klassen."""
    if not notes:
        return {"key": "?", "mode": "?", "confidence": 0.0}

    chroma = [0.0] * 12
    for n in notes:
        chroma[n["pitch"] % 12] += 1.0
    total = sum(chroma) or 1
    chroma = [c / total for c in chroma]

    import math
    def correlation(a, b):
        ma, mb = sum(a)/12, sum(b)/12
        num = sum((x-ma)*(y-mb) for x,y in zip(a,b))
        den = math.sqrt(sum((x-ma)**2 for x in a) * sum((y-mb)**2 for y in b))
        return num/den if den else 0

    best_key, best_mode, best_score = 0, "major", -999
    for root in range(12):
        rotated = chroma[root:] + chroma[:root]
        maj_score = correlation(rotated, _MAJOR)
        min_score = correlation(rotated, _MINOR)
        if maj_score > best_score:
            best_score, best_key, best_mode = maj_score, root, "major"
        if min_score > best_score:
            best_score, best_key, best_mode = min_score, root, "minor"

    return {
        "key":        NOTE_NAMES[best_key],
        "mode":       best_mode,
        "confidence": round(best_score, 3),
        "full_key":   f"{NOTE_NAMES[best_key]} {best_mode}",
    }


def detect_chords(notes: list[dict], step_tolerance: int = 1) -> list[str]:
    """Erkennt akkordische Strukturen (gleichzeitige Noten)."""
    if not notes:
        return []

    # Noten nach Step gruppieren (Toleranz ±1 Step)
    step_groups: dict[int, list[int]] = {}
    for n in notes:
        step = n["step"]
        key_step = None
        for s in step_groups:
            if abs(s - step) <= step_tolerance:
                key_step = s
                break
        if key_step is None:
            key_step = step
            step_groups[key_step] = []
        step_groups[key_step].append(n["pitch"] % 12)

    chords = []
    CHORD_NAMES = {
        frozenset([0,4,7]):   "maj",  frozenset([0,3,7]): "min",
        frozenset([0,4,7,11]):"maj7", frozenset([0,3,7,10]):"min7",
        frozenset([0,4,7,10]):"dom7", frozenset([0,3,6]):  "dim",
        frozenset([0,4,8]):   "aug",  frozenset([0,5,7]):  "sus4",
    }
    for step, pitches in sorted(step_groups.items()):
        pset = frozenset(p % 12 for p in pitches)
        if len(pset) >= 3:
            chord_type = CHORD_NAMES.get(pset, "chord")
            root = NOTE_NAMES[min(pitches) % 12]
            chords.append(f"{root}{chord_type}")

    return chords[:8]   # max 8 Akkorde


def describe_rhythm(notes: list[dict], loop_beats: float) -> dict:
    """Beschreibt das Rhythmus-Pattern."""
    if not notes:
        return {"density": 0, "pattern": "leer", "quantization": "?"}

    steps = sorted(set(n["step"] for n in notes))
    total_steps = int(loop_beats / STEP_BEATS) if loop_beats > 0 else 32
    density = len(steps) / total_steps if total_steps > 0 else 0

    # Quantisierung erkennen
    step_diffs = [steps[i+1] - steps[i] for i in range(len(steps)-1)]
    if step_diffs:
        min_diff = min(step_diffs)
        quant = "1/16" if min_diff == 1 else "1/8" if min_diff == 2 else "1/4" if min_diff == 4 else f"1/{int(16/min_diff)}"
    else:
        quant = "1/16"

    # Beat-Positionen auf bekannte Positionen mappen
    on_beat1 = any(s % 16 == 0 for s in steps)
    on_beat3 = any(s % 16 == 8 for s in steps)
    on_beat2 = any(s % 16 == 4 for s in steps)
    on_beat4 = any(s % 16 == 12 for s in steps)

    if density > 0.7:
        pattern = "sehr dicht / durchgehend"
    elif density > 0.4:
        pattern = "dicht / rhythmisch"
    elif on_beat1 and on_beat3 and density < 0.3:
        pattern = "auf Beat 1+3 (Off-Beat)"
    elif on_beat2 and on_beat4:
        pattern = "auf Beat 2+4 (Backbeat)"
    elif density < 0.15:
        pattern = "spärlich / melodisch"
    else:
        pattern = "rhythmisch"

    return {
        "density":       round(density, 3),
        "quantization":  quant,
        "pattern":       pattern,
        "note_count":    len(notes),
        "unique_steps":  len(steps),
        "loop_beats":    loop_beats,
    }


def describe_melody(notes: list[dict]) -> dict:
    """Beschreibt Melodie-Kontur und Ambitus."""
    if not notes:
        return {}
    pitches = sorted(set(n["pitch"] for n in notes))
    if len(pitches) < 2:
        return {"range_semitones": 0, "ambitus": "eintönig", "pitch_names": [NOTE_NAMES[p%12] for p in pitches]}

    span = pitches[-1] - pitches[0]
    ambitus = "sehr eng (<4 Ht)" if span < 4 else \
              "eng (4-7 Ht)" if span < 8 else \
              "mittel (8-12 Ht)" if span < 13 else \
              "weit (1-2 Oktaven)" if span < 25 else \
              "sehr weit (>2 Oktaven)"

    return {
        "range_semitones": span,
        "ambitus":         ambitus,
        "lowest":          NOTE_NAMES[pitches[0]%12],
        "highest":         NOTE_NAMES[pitches[-1]%12],
        "pitch_names":     list(dict.fromkeys(NOTE_NAMES[p%12] for p in pitches)),  # unique, ordered
    }


def build_content(track_name: str, project: str, key_info: dict,
                  rhythm: dict, melody: dict, chords: list[str]) -> str:
    lines = [f"**MIDI-Clip: {track_name}** — {project}"]
    if key_info.get("key") != "?":
        lines.append(f"Tonart: {key_info['full_key']} (Konfidenz {key_info['confidence']:.2f})")
    if chords:
        lines.append(f"Akkorde: {', '.join(chords)}")
    lines.append(f"Rhythmus: {rhythm.get('pattern','')} · {rhythm.get('quantization','')} · "
                 f"{rhythm.get('density',0):.0%} Dichte · {rhythm.get('note_count',0)} Noten")
    if melody.get("ambitus"):
        lines.append(f"Ambitus: {melody['ambitus']} ({melody.get('lowest','?')} – {melody.get('highest','?')})")
        if melody.get("pitch_names"):
            lines.append(f"Töne: {', '.join(melody['pitch_names'])}")
    return "\n".join(lines)


# ── Neo4j Storage ─────────────────────────────────────────────────────────────

def store_midi_clip(track_idx: int, track_name: str, project: str,
                    raw_notes: list[dict], loop_beats: float,
                    key_info: dict, rhythm: dict, melody: dict,
                    chords: list[str],
                    scene_idx: int = 0, scene_name: str = "",
                    drum_pad_map: dict | None = None) -> None:
    """drum_pad_map: {midi_note: pad_name} für Drum Machine Tracks."""
    import json as _json
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    # Drum-Annotierung: jedem Note-Dict den Pad-Namen hinzufügen
    if drum_pad_map:
        raw_notes = [
            {**n, "drum_sound": drum_pad_map.get(n["pitch"], "")}
            for n in raw_notes
        ]

    # Szenen-Info in Content einbauen
    scene_suffix = f" | Szene: {scene_name}" if scene_name else ""
    content = build_content(track_name + scene_suffix, project, key_info, rhythm, melody, chords)
    try:
        emb = get_embeddings().embed_documents([content])[0]
    except RuntimeError:
        emb = None  # Embedding-Server nicht verfügbar — Metadaten trotzdem speichern

    # Raw Notes als JSON für Rekonstruktion
    notes_json = _json.dumps(raw_notes, ensure_ascii=False)

    with neo4j_session() as s:
        # MERGE per Track + Szene (Matrix-Key: ein Node pro Track×Scene)
        cypher = """
            MERGE (n:MidiClip {track_name: $name, project: $project, scene_name: $scene_name})
            SET n.track_name      = $name,
                n.track_index     = $ti,
                n.scene_idx       = $scene_idx,
                n.scene_name      = $scene_name,
                n.key             = $key,
                n.mode            = $mode,
                n.key_confidence  = $key_conf,
                n.full_key        = $full_key,
                n.chords          = $chords,
                n.rhythm_pattern  = $pattern,
                n.quantization    = $quant,
                n.note_density    = $density,
                n.note_count      = $note_count,
                n.ambitus         = $ambitus,
                n.pitch_names     = $pitch_names,
                n.loop_beats      = $loop_beats,
                n.notes_json      = $notes_json,
                n.drum_pad_map    = $drum_pad_map,
                n.content         = $content,
                n.source          = $source
        """
        if emb is not None:
            cypher += ", n.embedding = $emb"
        s.run(cypher, ti=track_idx, project=project, scene_idx=scene_idx,
             scene_name=scene_name, name=track_name,
             key=key_info.get("key","?"), mode=key_info.get("mode","?"),
             key_conf=key_info.get("confidence",0),
             full_key=key_info.get("full_key","?"),
             chords=chords, pattern=rhythm.get("pattern",""),
             quant=rhythm.get("quantization",""),
             density=rhythm.get("density",0), note_count=rhythm.get("note_count",0),
             ambitus=melody.get("ambitus",""), pitch_names=melody.get("pitch_names",[]),
             loop_beats=loop_beats, notes_json=notes_json,
             drum_pad_map=_json.dumps(drum_pad_map or {}, ensure_ascii=False),
             content=content,
             source=f"MidiClip:{project}/Track{track_idx}/Scene{scene_idx}",
             emb=emb)

        # HNSW-Index
        try:
            s.run("""
                CREATE VECTOR INDEX midiclip_embedding IF NOT EXISTS
                FOR (n:MidiClip) ON n.embedding
                OPTIONS {indexConfig: {`vector.dimensions`: 768,
                                       `vector.similarity_function`: 'cosine'}}
            """)
        except Exception: pass

        # Mit SoundRecipe verknüpfen
        s.run("""
            MATCH (mc:MidiClip {track_index: $ti, project: $project, scene_idx: $scene_idx})
            MATCH (sr:SoundRecipe {track_index: $ti, project: $project})
            MERGE (mc)-[:CLIP_OF]->(sr)
            SET sr.midi_key = $key, sr.midi_mode = $mode
        """, ti=track_idx, project=project, scene_idx=scene_idx,
             key=key_info.get("key","?"), mode=key_info.get("mode","?"))

        # Mit Scene-Node verknüpfen (falls vorhanden)
        if scene_idx > 0:
            s.run("""
                MATCH (mc:MidiClip {track_index: $ti, project: $project, scene_idx: $scene_idx})
                MATCH (sc:Scene {idx: $scene_idx, project: $project})
                MERGE (mc)-[:IN_SCENE]->(sc)
            """, ti=track_idx, project=project, scene_idx=scene_idx)


# ── Audio-Analyse (integriert) ────────────────────────────────────────────────

def _run_audio_analysis(project: str, has_embed: bool) -> None:
    """Analysiert alle WAV-Dateien im samples/-Verzeichnis des Projekts."""
    from scripts.ingest_audio_samples import analyze_file, store_samples, PROJECTS_DIR

    samples_dir = PROJECTS_DIR / project / "samples"
    if not samples_dir.exists():
        print(f"\n[audio] Kein samples/-Ordner gefunden: {samples_dir}")
        return

    wav_files = sorted(samples_dir.glob("*.wav"))
    if not wav_files:
        print(f"\n[audio] Keine WAV-Dateien in {samples_dir}")
        return

    print(f"\n[audio] Analysiere {len(wav_files)} WAV-Dateien …")
    features = []
    for wav in wav_files:
        print(f"  {wav.name:<50}", end="", flush=True)
        feat = analyze_file(wav)
        if feat:
            features.append(feat)
            print(f"{feat['duration_s']:>6.1f}s  {feat['category']:<20} {feat['key_note']} ({feat['key_conf']:.0%})")
        else:
            print("übersprungen")
        time.sleep(0.05)

    if not features:
        print("[audio] Keine Ergebnisse")
        return

    if not has_embed:
        print(f"[audio] ⚠️  Embedding-Server fehlt — AudioSample-Nodes ohne Vektoren")
        # Metadaten ohne Embeddings speichern
        from src.knowledge.neo4j_graph import session as neo4j_session
        with neo4j_session() as s:
            for feat in features:
                from scripts.ingest_audio_samples import _build_content
                content = _build_content(feat, project)
                s.run("""
                    MERGE (n:AudioSample {filename: $filename, project: $project})
                    SET n.category      = $category,
                        n.duration_s    = $duration_s,
                        n.rms           = $rms,
                        n.centroid_hz   = $centroid_hz,
                        n.key_note      = $key_note,
                        n.key_conf      = $key_conf,
                        n.onset_density = $onset_density,
                        n.content       = $content,
                        n.source        = $source
                """, filename=feat["filename"], project=project,
                     category=feat["category"], duration_s=feat["duration_s"],
                     rms=feat["rms"], centroid_hz=feat["centroid_hz"],
                     key_note=feat["key_note"], key_conf=feat["key_conf"],
                     onset_density=feat["onset_density"], content=content,
                     source=f"AudioSample:{project}/{feat['filename']}")
        print(f"✅  {len(features)} AudioSample-Nodes (ohne Embedding) in Neo4j")
    else:
        stored = store_samples(features, project)
        print(f"✅  {stored} AudioSample-Nodes in Neo4j")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="MIDI-Clip-Analyse → Neo4j")
    parser.add_argument("--project", default="Chee - Hey Now")
    parser.add_argument("--track",   type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from src.agent.osc.project_scan import (
        query_project_snapshot, query_track_clip_notes, query_drum_pads
    )

    print(f"[scan] Lade Projekt-Snapshot für '{args.project}' …")
    try:
        snapshot = query_project_snapshot(args.project, timeout=8.0)
    except RuntimeError as e:
        print(f"❌  {e}")
        sys.exit(1)

    print(f"  {len(snapshot.tracks)} Tracks, {len(snapshot.scenes)} Szenen: "
          f"{[s.name for s in snapshot.scenes]}")

    # Melodische Tracks priorisieren (Percussion hat kaum harmonischen Inhalt)
    SKIP_ROLES = {"Kick", "Snare/Clap", "Hi-Hat/Percussion"}
    from src.knowledge.neo4j_graph import session as neo4j_session
    with neo4j_session() as s:
        role_map = {r["idx"]: r["role"] for r in s.run("""
            MATCH (sr:SoundRecipe {project: $p})
            RETURN sr.track_index AS idx, sr.role AS role
        """, p=args.project).data()}

    # ── Drum Pad Mapping: track_idx → {midi_note → pad_name} ─────────────────
    # Für jeden Track mit Drum Machine Gerät die Pad-Namen abfragen.
    # Erfordert die neue Extension mit /agent/track/drum-pads Endpoint.
    drum_pad_maps: dict[int, dict[int, str]] = {}
    print("  Prüfe Drum Machine Pads …")
    for track in snapshot.instrument_tracks():
        devices = getattr(track, "devices", []) or []
        is_drum = any("drum machine" in d.lower() for d in devices)
        if not is_drum:
            continue
        pad_data = query_drum_pads(track.idx, timeout=2.5)
        pads = pad_data.get("pads", [])
        if pads:
            note_map = {p["note"]: p["name"] for p in pads if p.get("name")}
            drum_pad_maps[track.idx] = note_map
            pad_str = ", ".join(f"{p['note']}={p['name']}" for p in pads[:6])
            print(f"    Track {track.idx}: {track.name} → {len(pads)} Pads: {pad_str} …")
        elif pad_data.get("has_drum_pads") is False:
            pass  # kein Drum Machine — normal
    if not drum_pad_maps:
        print("    (keine Drum Machine Pads gefunden — Extension ggf. noch nicht aktuell)")

    results = []
    for track in snapshot.instrument_tracks():
        idx  = track.idx
        name = track.name
        if args.track and idx != args.track:
            continue
        role = role_map.get(idx, track.role or "")
        if role in SKIP_ROLES and not args.track:
            print(f"  Track {idx:>2}: {name:<28} [{role}] — übersprungen (Percussion)")
            continue

        # Alle Szenen mit Content aus Snapshot (Matrix) — O(1) pro Slot
        scene_slots = track.clips_with_notes()
        if not scene_slots and not args.track:
            print(f"  Track {idx:>2}: {name:<28} — kein Slot mit Content")
            continue

        # Fallback: wenn Snapshot keinen Content zeigt, Slot 0 versuchen
        if not scene_slots:
            scene_slots = [0]

        for scene_idx in scene_slots:
            sc = snapshot.scene_by_idx(scene_idx)
            scene_name = sc.name if sc else f"Slot{scene_idx}"

            print(f"  Track {idx:>2}: {name:<28} [{scene_name}] ", end="", flush=True)
            clip = query_track_clip_notes(idx, scene_idx=scene_idx, timeout=5.0)
            notes = clip.get("notes", [])
            beats = clip.get("loop_beats", 0.0)

            if not notes:
                print("leer")
                continue

            key_info = detect_key(notes)
            chords   = detect_chords(notes)
            rhythm   = describe_rhythm(notes, beats)
            melody   = describe_melody(notes)

            print(f"{len(notes):>3} Noten · {key_info['full_key']:<15} "
                  f"{rhythm['pattern'][:20]}")
            if chords:
                print(f"             Akkorde: {', '.join(chords)}")

            pad_map = drum_pad_maps.get(idx, {})
            results.append((idx, name, notes, beats, key_info, rhythm, melody, chords,
                            scene_idx, scene_name, pad_map))
            time.sleep(0.3)

    if args.dry_run:
        print(f"\n[dry-run] {len(results)} Tracks analysiert — nichts gespeichert")
        return

    from src.knowledge.store import _server_available
    has_embed = _server_available() is not None

    label = "[embed]" if has_embed else "[store] (kein Embedding-Server — nur Metadaten)"
    print(f"\n{label} Speichere {len(results)} MidiClip-Nodes …")
    for idx, name, notes, beats, key_info, rhythm, melody, chords, scene_idx, scene_name, pad_map in results:
        store_midi_clip(idx, name, args.project, notes, beats,
                        key_info, rhythm, melody, chords,
                        scene_idx=scene_idx, scene_name=scene_name,
                        drum_pad_map=pad_map)

    n_tracks = len({r[0] for r in results})
    n_scenes = len({r[8] for r in results})
    print(f"✅  {len(results)} MidiClip-Nodes in Neo4j  [{n_tracks} Tracks × {n_scenes} Szenen]")
    if not has_embed:
        print("⚠️   Embeddings fehlen → Vektorsuche für neue Nodes nicht aktiv")
        print("    Nachholen mit: make embed-server  dann  make ingest-midi")
    else:
        print("Durchsuchbar via query_bitwig_docs")

    # ── Audio-Samples analysieren ─────────────────────────────────────────────
    if not args.dry_run:
        _run_audio_analysis(args.project, has_embed)


if __name__ == "__main__":
    main()
