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
                    chords: list[str]) -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    content = build_content(track_name, project, key_info, rhythm, melody, chords)
    emb = get_embeddings().embed_documents([content])[0]

    with neo4j_session() as s:
        s.run("""
            MERGE (n:MidiClip {track_index: $ti, project: $project})
            SET n.track_name      = $name,
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
                n.content         = $content,
                n.source          = $source,
                n.embedding       = $emb
        """, ti=track_idx, project=project, name=track_name,
             key=key_info.get("key","?"), mode=key_info.get("mode","?"),
             key_conf=key_info.get("confidence",0),
             full_key=key_info.get("full_key","?"),
             chords=chords, pattern=rhythm.get("pattern",""),
             quant=rhythm.get("quantization",""),
             density=rhythm.get("density",0), note_count=rhythm.get("note_count",0),
             ambitus=melody.get("ambitus",""), pitch_names=melody.get("pitch_names",[]),
             loop_beats=loop_beats, content=content,
             source=f"MidiClip:{project}/Track{track_idx}",
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
            MATCH (mc:MidiClip {track_index: $ti, project: $project})
            MATCH (sr:SoundRecipe {track_index: $ti, project: $project})
            MERGE (mc)-[:CLIP_OF]->(sr)
            SET sr.midi_key = $key, sr.midi_mode = $mode
        """, ti=track_idx, project=project,
             key=key_info.get("key","?"), mode=key_info.get("mode","?"))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="MIDI-Clip-Analyse → Neo4j")
    parser.add_argument("--project", default="Chee - Hey Now")
    parser.add_argument("--track",   type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from src.agent.osc.project_scan import scan_project, query_track_clip_notes

    print(f"[scan] Lade Tracks von '{args.project}' …")
    project_data = scan_project(timeout=5.0)
    all_tracks = project_data.get("tracks", [])
    if not all_tracks and not project_data.get("_raw"):
        print("❌  Bitwig nicht erreichbar")
        sys.exit(1)

    # Melodische Tracks priorisieren (Percussion hat kaum harmonischen Inhalt)
    SKIP_ROLES = {"Kick", "Snare/Clap", "Hi-Hat/Percussion"}
    from src.knowledge.neo4j_graph import session as neo4j_session
    with neo4j_session() as s:
        role_map = {r["idx"]: r["role"] for r in s.run("""
            MATCH (sr:SoundRecipe {project: $p})
            RETURN sr.track_index AS idx, sr.role AS role
        """, p=args.project).data()}

    results = []
    for track in all_tracks:
        idx  = track.get("idx", 0)
        name = track.get("name", f"Track {idx}")
        if args.track and idx != args.track:
            continue
        role = role_map.get(idx, "")
        if role in SKIP_ROLES and not args.track:
            print(f"  Track {idx:>2}: {name:<28} [{role}] — übersprungen (Percussion)")
            continue

        print(f"  Track {idx:>2}: {name:<28} ", end="", flush=True)
        clip = query_track_clip_notes(idx, timeout=5.0)
        notes = clip.get("notes", [])
        beats = clip.get("loop_beats", 0.0)

        if not notes:
            print("kein Clip / leer")
            continue

        key_info = detect_key(notes)
        chords   = detect_chords(notes)
        rhythm   = describe_rhythm(notes, beats)
        melody   = describe_melody(notes)

        print(f"{len(notes):>3} Noten · {key_info['full_key']:<15} "
              f"{rhythm['pattern'][:20]}")
        if chords:
            print(f"           Akkorde: {', '.join(chords)}")

        results.append((idx, name, notes, beats, key_info, rhythm, melody, chords))
        time.sleep(0.3)

    if args.dry_run:
        print(f"\n[dry-run] {len(results)} Tracks analysiert — nichts gespeichert")
        return

    print(f"\n[embed] Speichere {len(results)} MidiClip-Nodes …")
    for idx, name, notes, beats, key_info, rhythm, melody, chords in results:
        store_midi_clip(idx, name, args.project, notes, beats,
                        key_info, rhythm, melody, chords)
    print(f"✅  {len(results)} MidiClip-Nodes in Neo4j")
    print("Durchsuchbar via query_bitwig_docs")


if __name__ == "__main__":
    main()
