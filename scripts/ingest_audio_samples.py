"""
Analysiert WAV-Dateien aus Bitwig-Projekten mit librosa und speichert
AudioSample-Nodes mit Embeddings in Neo4j.

Extrahiert: Tempo, Key, Helligkeit, Energie, Onset-Dichte, MFCC-Profil,
Dauer, ZCR (Tonalität) — alles als semantischer Text + Embedding.

Ausführen:
    python scripts/ingest_audio_samples.py --project "Chee - Hey Now"
    python scripts/ingest_audio_samples.py --project "Ferrous Rhythm"
    python scripts/ingest_audio_samples.py --dir "/pfad/zum/samples/ordner"
    python scripts/ingest_audio_samples.py --project "Chee - Hey Now" --dry-run
    python scripts/ingest_audio_samples.py --project "Chee - Hey Now" --reset
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROJECTS_DIR = Path("/home/sija/Bitwig Studio/Projects")
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# ── Semantische Beschreibung ──────────────────────────────────────────────────

def _brightness(centroid_hz: float) -> str:
    if centroid_hz < 300:   return "Sub-Bass (unter 300 Hz)"
    if centroid_hz < 800:   return "sehr dunkel/warm (Bass-Bereich)"
    if centroid_hz < 1500:  return "dunkel/warm"
    if centroid_hz < 3000:  return "mittig/ausgewogen"
    if centroid_hz < 6000:  return "hell/präsent"
    if centroid_hz < 10000: return "sehr hell/air"
    return "extrem hell/crispy"

def _energy(rms: float) -> str:
    if rms < 0.01:  return "sehr leise/subtil"
    if rms < 0.05:  return "leise"
    if rms < 0.12:  return "moderat"
    if rms < 0.25:  return "laut"
    return "sehr laut/heiß"

def _density(onsets_per_sec: float) -> str:
    if onsets_per_sec < 0.5: return "sustained/Pad (kaum Transienten)"
    if onsets_per_sec < 2:   return "spärlich rhythmisch"
    if onsets_per_sec < 5:   return "rhythmisch"
    if onsets_per_sec < 10:  return "dicht/rhythmisch"
    return "sehr dicht/perkussiv"

def _tonality(zcr: float) -> str:
    if zcr < 0.04:  return "sehr tonal/Sinus-artig"
    if zcr < 0.08:  return "tonal"
    if zcr < 0.15:  return "gemischt tonal/rauschig"
    if zcr < 0.25:  return "rauschig"
    return "Noise/White Noise"

def _classify_file(filename: str) -> str:
    n = filename.lower()
    if "bounce" in n:     return "Bounce/Render"
    if any(k in n for k in ["vox", "vocal", "voice", "hey", "breathe", "osr"]):
        return "Vocals"
    if any(k in n for k in ["kick", "bd"]):   return "Kick"
    if any(k in n for k in ["clap", "snare"]): return "Clap/Snare"
    if any(k in n for k in ["hat", "cymbal", "sandy"]): return "Hi-Hat/Cymbal"
    if any(k in n for k in ["bass", "sub"]):  return "Bass"
    if any(k in n for k in ["stringer", "string"]): return "Strings/Loop"
    if any(k in n for k in ["loop", "texture", "loopy"]): return "Loop/Texture"
    if any(k in n for k in ["pluck", "arp"]): return "Pluck/Arp"
    return "Sample"

def _match_track_name(filename: str) -> str | None:
    """Versucht eine Track-Entsprechung im Projekt zu finden."""
    stem = Path(filename).stem.lower()
    # bounce-Dateien: "Poly Grid-bounce-1" → "Poly Grid"
    stem = stem.replace("-bounce-1", "").replace("-bounce-2", "")
    stem = stem.replace("-bounce", "")
    # Bekannte Mappings
    mappings = {
        "submotion":        "SUBMOTION-Low",
        "loopy textures":   "Loopy Textures",
        "sine pluck":       "Sine Pluck 1",
        "stringer":         "Stringer",
        "poly grid":        "Sine Pluck 1",
        "polysynth":        "Sharp Arp",
        "clap":             "Clap/Snare/Rimshot",
        "e-hat":            "Hats & Percs",
        "vox and sound fx": "VOX and FX",
        "pao":              "Dissonant Pad",
        "powa":             "Swarm Bass Pad",
    }
    for key, track in mappings.items():
        if key in stem:
            return track
    return None


# ── Analyse ───────────────────────────────────────────────────────────────────

def analyze_file(path: Path, max_duration: float = 30.0) -> dict | None:
    """Analysiert eine WAV-Datei und gibt einen Feature-Dict zurück."""
    try:
        import librosa
        y, sr = librosa.load(str(path), sr=None, mono=True, duration=max_duration)
        if len(y) < sr * 0.1:  # < 100ms → überspringen
            return None

        duration = len(y) / sr

        # Grundfeatures
        rms = float(librosa.feature.rms(y=y).mean())

        # Spektral
        centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
        bandwidth = float(librosa.feature.spectral_bandwidth(y=y, sr=sr).mean())
        rolloff   = float(librosa.feature.spectral_rolloff(y=y, sr=sr, roll_percent=0.85).mean())
        zcr       = float(librosa.feature.zero_crossing_rate(y=y).mean())

        # Rhythmik
        try:
            tempo_arr, _ = librosa.beat.beat_track(y=y, sr=sr)
            tempo = float(np.atleast_1d(tempo_arr)[0])
        except Exception:
            tempo = 0.0

        onsets = librosa.onset.onset_detect(y=y, sr=sr)
        onset_density = len(onsets) / duration if duration > 0 else 0.0

        # Tonalität / Key
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
        key_idx = int(np.argmax(chroma))
        key_note = NOTES[key_idx]
        key_confidence = float(chroma[key_idx] / chroma.sum()) if chroma.sum() > 0 else 0.0

        # MFCC (timbrale Signatur, 13 Koeffizienten)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13).mean(axis=1).tolist()

        category = _classify_file(path.name)
        track_match = _match_track_name(path.name)

        return {
            "filename":      path.name,
            "category":      category,
            "track_match":   track_match,
            "duration_s":    round(duration, 2),
            "sample_rate":   sr,
            "rms":           round(rms, 4),
            "centroid_hz":   round(centroid, 1),
            "bandwidth_hz":  round(bandwidth, 1),
            "rolloff_hz":    round(rolloff, 1),
            "zcr":           round(zcr, 4),
            "tempo_bpm":     round(tempo, 1),
            "onset_density": round(onset_density, 2),
            "key_note":      key_note,
            "key_conf":      round(key_confidence, 3),
            "mfcc":          [round(v, 2) for v in mfcc],
        }
    except Exception as e:
        print(f"    Fehler bei {path.name}: {e}")
        return None


def _build_content(feat: dict, project_name: str) -> str:
    """Erstellt lesbaren Text für Embedding + RAG."""
    lines = [
        f"**Audio-Sample: {feat['filename']}** [{feat['category']}] — {project_name}",
        f"Dauer: {feat['duration_s']:.1f}s | Sample Rate: {feat['sample_rate']} Hz",
        f"Energie: {_energy(feat['rms'])} (RMS={feat['rms']:.3f})",
        f"Klangfarbe: {_brightness(feat['centroid_hz'])} (Centroid={feat['centroid_hz']:.0f} Hz)",
        f"Tonalität: {_tonality(feat['zcr'])}",
        f"Rhythmik: {_density(feat['onset_density'])} ({feat['onset_density']:.1f} Onsets/s)",
    ]
    if feat["tempo_bpm"] > 20:
        lines.append(f"Tempo: {feat['tempo_bpm']:.1f} BPM")
    if feat["key_conf"] > 0.15:
        lines.append(f"Tonart: {feat['key_note']} (Konfidenz {feat['key_conf']:.0%})")
    if feat["track_match"]:
        lines.append(f"Gehört zu Track: {feat['track_match']}")
    # Komprimierte MFCC-Beschreibung
    m = feat["mfcc"]
    if abs(m[0]) > 200:
        lines.append(f"Timbre: Bass-reich (MFCC[0]={m[0]:.0f})" if m[0] < -200 else
                     f"Timbre: Mittelton-reich (MFCC[0]={m[0]:.0f})")
    return "\n".join(lines)


# ── Neo4j Storage ─────────────────────────────────────────────────────────────

def store_samples(features: list[dict], project_name: str) -> int:
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    print(f"\n[embed] Lade Embedding-Modell …")
    emb_model = get_embeddings()
    dim = len(emb_model.embed_query("test"))
    print(f"[embed] Bereit — Dimension: {dim}")

    # HNSW-Index anlegen
    with neo4j_session() as s:
        try:
            s.run("""
                CREATE VECTOR INDEX audio_sample_embedding IF NOT EXISTS
                FOR (n:AudioSample) ON n.embedding
                OPTIONS {indexConfig: {`vector.dimensions`: $dim,
                                       `vector.similarity_function`: 'cosine'}}
            """, dim=dim)
        except Exception:
            pass

    stored = 0
    t0 = time.time()
    with neo4j_session() as s:
        for feat in features:
            content = _build_content(feat, project_name)
            vec = emb_model.embed_documents([content])[0]

            s.run("""
                MERGE (n:AudioSample {filename: $filename, project: $project})
                SET n.category     = $category,
                    n.duration_s   = $duration_s,
                    n.sample_rate  = $sample_rate,
                    n.rms          = $rms,
                    n.centroid_hz  = $centroid_hz,
                    n.bandwidth_hz = $bandwidth_hz,
                    n.rolloff_hz   = $rolloff_hz,
                    n.zcr          = $zcr,
                    n.tempo_bpm    = $tempo_bpm,
                    n.onset_density= $onset_density,
                    n.key_note     = $key_note,
                    n.key_conf     = $key_conf,
                    n.content      = $content,
                    n.source       = $source,
                    n.embedding    = $embedding
            """,
            filename=feat["filename"], project=project_name,
            category=feat["category"], duration_s=feat["duration_s"],
            sample_rate=feat["sample_rate"], rms=feat["rms"],
            centroid_hz=feat["centroid_hz"], bandwidth_hz=feat["bandwidth_hz"],
            rolloff_hz=feat["rolloff_hz"], zcr=feat["zcr"],
            tempo_bpm=feat["tempo_bpm"], onset_density=feat["onset_density"],
            key_note=feat["key_note"], key_conf=feat["key_conf"],
            content=content,
            source=f"AudioSample:{project_name}/{feat['filename']}",
            embedding=vec,
            )

            # SAMPLED_IN-Kante zu SoundRecipe wenn Zuordnung möglich
            if feat.get("track_match"):
                s.run("""
                    MATCH (sr:SoundRecipe {project: $project})
                    WHERE sr.track_name = $track_name
                    MATCH (a:AudioSample {filename: $filename, project: $project})
                    MERGE (a)-[:SAMPLED_IN]->(sr)
                """, project=project_name,
                     track_name=feat["track_match"],
                     filename=feat["filename"])
            stored += 1

    print(f"  {stored} AudioSample-Nodes gespeichert ({time.time()-t0:.1f}s)")
    return stored


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="WAV-Analyse → Neo4j AudioSample-Nodes")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", help="Bitwig-Projektname (sucht in ~/Bitwig Studio/Projects/)")
    group.add_argument("--dir",     help="Direkter Pfad zum samples/-Ordner")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset",   action="store_true")
    parser.add_argument("--max-duration", type=float, default=30.0,
                        help="Max. Analysedauer pro Datei in Sekunden (Standard: 30)")
    args = parser.parse_args()

    # Samples-Ordner finden
    if args.dir:
        samples_dir = Path(args.dir)
        project_name = samples_dir.parent.name
    else:
        project_dir = PROJECTS_DIR / args.project
        samples_dir = project_dir / "samples"
        project_name = args.project

    if not samples_dir.exists():
        print(f"❌  Samples-Ordner nicht gefunden: {samples_dir}")
        sys.exit(1)

    wav_files = sorted(samples_dir.glob("*.wav"))
    if not wav_files:
        print(f"❌  Keine WAV-Dateien in: {samples_dir}")
        sys.exit(1)

    print(f"[analyse] {len(wav_files)} WAV-Dateien in: {samples_dir}")
    print(f"[analyse] Projekt: {project_name}\n")

    features: list[dict] = []
    for i, wav in enumerate(wav_files, 1):
        size_kb = wav.stat().st_size // 1024
        print(f"  [{i:>2}/{len(wav_files)}] {wav.name:<55} ({size_kb:>5} KB) … ", end="", flush=True)
        feat = analyze_file(wav, max_duration=args.max_duration)
        if feat is None:
            print("übersprungen")
            continue
        feat["project"] = project_name
        features.append(feat)
        cat  = feat["category"]
        bri  = _brightness(feat["centroid_hz"]).split("(")[0].strip()
        den  = _density(feat["onset_density"]).split("(")[0].strip()
        key  = f"{feat['key_note']} " if feat["key_conf"] > 0.15 else ""
        print(f"{cat:18} | {bri:20} | {den:22} | {key}{feat['tempo_bpm']:.0f} BPM")

    print(f"\n[summary] {len(features)} Dateien analysiert\n")

    if args.dry_run:
        print("[dry-run] Beispiel-Content:\n" + "─" * 60)
        if features:
            print(_build_content(features[0], project_name))
        return

    if args.reset:
        from src.knowledge.neo4j_graph import session as neo4j_session
        with neo4j_session() as s:
            c = s.run("MATCH (n:AudioSample {project:$p}) DELETE n RETURN count(n) AS c",
                      p=project_name).single()["c"]
            print(f"[reset] {c} AudioSample-Nodes gelöscht")

    stored = store_samples(features, project_name)

    # Vektorsuche auch für AudioSample in knowledge_tool aktivieren?
    print(f"\n✅  {stored} AudioSample-Nodes mit Embeddings in Neo4j")
    print(f"   SAMPLED_IN-Kanten zu SoundRecipe-Nodes gesetzt")


if __name__ == "__main__":
    main()
