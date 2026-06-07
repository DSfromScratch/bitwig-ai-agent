"""
Song-Lern-Tool: lädt YouTube-Audio, analysiert es und schreibt es als
(:Song)-[:BY]->(:Artist) in Neo4j inklusive Audio-Features + Embedding.

⚠️  Nur für PRIVATE Nutzung (Agenten-Training). Audio-Files werden nach der
   Analyse standardmäßig **nicht** persistiert (only_features=True), nur
   abgeleitete Features (BPM, Key, MFCC-Profil, Sections, ggf. MIDI-Transkription).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()
log = logging.getLogger("bitwig-agent")

_DOWNLOAD_DIR = Path(os.getenv("SONG_LEARN_CACHE", "/tmp/bitwig_agent_songs"))
_KEEP_AUDIO = os.getenv("SONG_LEARN_KEEP_AUDIO", "0") == "1"
_MIDI_TRANSCRIBE = os.getenv("SONG_LEARN_TRANSCRIBE_MIDI", "0") == "1"


# ── 1. YouTube-Download (yt-dlp) ────────────────────────────────────────────

def _download_youtube_audio(url: str, out_dir: Path) -> Path | None:
    """Lädt YouTube-Audio als WAV/M4A und gibt Pfad zurück."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import yt_dlp
    except ImportError:
        log.error("yt-dlp nicht installiert")
        return None

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "192",
        }],
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            vid_id = info.get("id")
            return out_dir / f"{vid_id}.wav"
    except Exception as exc:
        log.error("yt-dlp Download fehlgeschlagen für %s: %s", url, exc)
        return None


# ── 2. Audio-Feature-Extraktion (librosa) ───────────────────────────────────

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _extract_features(audio_path: Path) -> dict[str, Any]:
    """Voll-Track-Analyse via librosa."""
    import librosa

    y, sr = librosa.load(str(audio_path), mono=True)
    duration = len(y) / sr

    tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key_idx = int(chroma.mean(axis=1).argmax())
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
    rms = librosa.feature.rms(y=y)
    zcr = librosa.feature.zero_crossing_rate(y=y)

    # Struktur via einfacher Segmentierung
    try:
        boundaries = librosa.segment.agglomerative(chroma, k=6)
        section_times = list(librosa.frames_to_time(boundaries, sr=sr))
    except Exception:
        section_times = []

    return {
        "duration_s": round(duration, 2),
        "bpm": round(float(tempo), 1),
        "beat_count": int(len(beats)),
        "key": _NOTE_NAMES[key_idx],
        "key_index": key_idx,
        "mfcc_mean": [round(float(x), 3) for x in mfcc.mean(axis=1)],
        "mfcc_std":  [round(float(x), 3) for x in mfcc.std(axis=1)],
        "spectral_centroid_mean": round(float(centroid.mean()), 1),
        "rms_mean": round(float(rms.mean()), 4),
        "rms_max":  round(float(rms.max()), 4),
        "zcr_mean": round(float(zcr.mean()), 4),
        "section_times_s": [round(float(t), 2) for t in section_times],
    }


# ── 3. Optional: MIDI-Transkription (basic-pitch) ───────────────────────────

def _transcribe_to_midi(audio_path: Path, midi_out: Path) -> Path | None:
    """Wandelt Audio in MIDI um. NUR aufgerufen wenn SONG_LEARN_TRANSCRIBE_MIDI=1
    (basic-pitch ist langsam: 30-60s pro 3-min-Song)."""
    try:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import predict_and_save

        midi_out.parent.mkdir(parents=True, exist_ok=True)
        predict_and_save(
            audio_path_list=[str(audio_path)],
            output_directory=str(midi_out.parent),
            save_midi=True, sonify_midi=False, save_model_outputs=False, save_notes=False,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
        )
        # basic-pitch nennt die Datei <name>_basic_pitch.mid
        return next(midi_out.parent.glob(f"{audio_path.stem}*basic_pitch.mid"), None)
    except Exception as exc:
        log.warning("basic-pitch Transkription fehlgeschlagen: %s", exc)
        return None


# ── 4. Persist in Neo4j ─────────────────────────────────────────────────────

def _build_content_text(artist: str, title: str, meta: dict, features: dict) -> str:
    """Baut den semantischen Text fürs Embedding."""
    parts = [f"Song: {title}", f"Künstler: {artist}"]
    mb = meta.get("musicbrainz") or {}
    ab = meta.get("acousticbrainz") or {}
    lf = meta.get("lastfm") or {}

    bpm = features.get("bpm") or ab.get("bpm")
    key = features.get("key") or ab.get("key")
    if bpm:
        parts.append(f"BPM: {bpm}")
    if key:
        scale = ab.get("scale", "")
        parts.append(f"Tonart: {key} {scale}".strip())
    if mb.get("tags"):
        parts.append(f"Tags (MusicBrainz): {', '.join(mb['tags'])}")
    if lf.get("tags"):
        parts.append(f"Tags (Last.fm): {', '.join(lf['tags'])}")
    for cat in ("genre_dortmund", "genre_rosamerica", "mood_happy",
                "mood_relaxed", "danceability", "voice_instrumental"):
        if ab.get(cat):
            parts.append(f"{cat}: {ab[cat]}")
    parts.append(f"Dauer: {features.get('duration_s')}s")
    parts.append(f"Helligkeit (spectral_centroid): {features.get('spectral_centroid_mean')} Hz")
    parts.append(f"Energie (RMS): {features.get('rms_mean')}")

    return " | ".join(str(p) for p in parts if p)


def _persist_to_neo4j(artist: str, title: str, meta: dict, features: dict,
                     youtube_url: str, midi_path: Path | None) -> dict:
    """Schreibt (:Song)-[:BY]->(:Artist) mit Features + Embedding."""
    from src.knowledge.neo4j_graph import session
    from src.knowledge.store import get_embeddings

    content = _build_content_text(artist, title, meta, features)
    emb = get_embeddings()
    vector = emb.embed_query(content)
    now = datetime.now(timezone.utc).isoformat()

    mb = meta.get("musicbrainz") or {}
    ab = meta.get("acousticbrainz") or {}
    lf = meta.get("lastfm") or {}

    props = {
        "name": title,
        "artist": artist,
        "source": "learn_song_from_youtube",
        "youtube_url": youtube_url,
        "mbid": mb.get("mbid"),
        "bpm": features.get("bpm"),
        "key": features.get("key"),
        "duration_s": features.get("duration_s"),
        "audio_features_json": json.dumps(features),
        "metadata_json": json.dumps({
            "musicbrainz_tags": mb.get("tags") or [],
            "lastfm_tags": lf.get("tags") or [],
            "ab_bpm": ab.get("bpm"),
            "ab_key": ab.get("key"),
            "ab_scale": ab.get("scale"),
            "ab_genre_dortmund": ab.get("genre_dortmund"),
            "ab_genre_rosamerica": ab.get("genre_rosamerica"),
            "ab_mood_happy": ab.get("mood_happy"),
            "ab_mood_relaxed": ab.get("mood_relaxed"),
            "ab_danceability": ab.get("danceability"),
            "ab_voice_instrumental": ab.get("voice_instrumental"),
        }),
        "midi_transcription_path": str(midi_path) if midi_path else None,
        "content": content,
        "embedding": vector,
        "updated_at": now,
    }

    with session() as s:
        s.run("""
            MERGE (a:Artist {name: $artist})
              ON CREATE SET a.created_at = $now
            MERGE (song:Song {name: $name, artist: $artist})
            SET song += $props
            MERGE (song)-[:BY]->(a)
        """, artist=artist, name=title, now=now, props=props)

    return {"persisted": True, "node_key": f"{artist} / {title}"}


# ── 5. Orchestrierung ───────────────────────────────────────────────────────

def _do_learn(artist: str, title: str, youtube_url: str, transcribe_midi: bool) -> dict:
    from src.agent.tools.song_metadata_tool import search_artist_song_dict

    t_start = time.time()
    meta = search_artist_song_dict(artist, title)
    log.info("[learn_song] Metadaten geladen (%.1fs)", time.time() - t_start)

    audio_path = _download_youtube_audio(youtube_url, _DOWNLOAD_DIR)
    if not audio_path or not audio_path.exists():
        return {"error": f"Download fehlgeschlagen: {youtube_url}", "meta": meta}
    log.info("[learn_song] Audio geladen: %s (%.1fs)",
             audio_path.name, time.time() - t_start)

    features = _extract_features(audio_path)
    log.info("[learn_song] Features extrahiert: BPM=%s Key=%s (%.1fs total)",
             features.get("bpm"), features.get("key"), time.time() - t_start)

    midi_path = None
    if transcribe_midi:
        midi_path = _transcribe_to_midi(audio_path, _DOWNLOAD_DIR / "midi" / f"{audio_path.stem}.mid")
        if midi_path:
            log.info("[learn_song] MIDI transkribiert: %s", midi_path.name)

    result = _persist_to_neo4j(artist, title, meta, features, youtube_url, midi_path)

    if not _KEEP_AUDIO and audio_path.exists():
        try:
            audio_path.unlink()
        except OSError:
            pass

    result["features"] = features
    result["meta"] = {
        "mbid": (meta.get("musicbrainz") or {}).get("mbid"),
        "mb_tags": (meta.get("musicbrainz") or {}).get("tags") or [],
        "ab_genre": (meta.get("acousticbrainz") or {}).get("genre_dortmund"),
        "ab_bpm": (meta.get("acousticbrainz") or {}).get("bpm"),
    }
    result["midi"] = str(midi_path) if midi_path else None
    result["total_seconds"] = round(time.time() - t_start, 1)
    return result


@tool
def learn_song_from_youtube(
    artist: str,
    title: str,
    youtube_url: str,
    transcribe_midi: bool = False,
) -> str:
    """Lernt einen Song: lädt YouTube-Audio, analysiert ihn, speichert in Neo4j.

    Pipeline:
      1. MusicBrainz/AcousticBrainz/Last.fm-Metadaten holen
      2. YouTube-Audio via yt-dlp herunterladen (temporär)
      3. librosa-Features extrahieren: BPM, Key, MFCC, Centroid, RMS, Sections
      4. (optional) basic-pitch MIDI-Transkription wenn transcribe_midi=True
      5. (:Song {name})-[:BY]->(:Artist {name}) in Neo4j mergen, inkl. Embedding
      6. Audio-Datei löschen (außer SONG_LEARN_KEEP_AUDIO=1)

    Args:
        artist: Künstler-Name
        title:  Song-Titel
        youtube_url: YouTube-URL des Songs
        transcribe_midi: Wenn True, läuft basic-pitch (langsam, ~30-60s).
                         Default False — Features reichen meistens.

    ⚠️ Nur privat / Agenten-Training. Audio-Files werden nicht persistiert.
    """
    if not youtube_url.startswith(("http://", "https://")):
        return f"[learn_song] Ungültige URL: {youtube_url}"

    try:
        result = _do_learn(artist, title, youtube_url, transcribe_midi)
    except Exception as exc:
        log.exception("learn_song_from_youtube fehlgeschlagen")
        return f"[learn_song] Fehler: {exc}"

    if "error" in result:
        return f"[learn_song] {result['error']}"

    feat = result["features"]
    meta = result["meta"]
    lines = [
        f"✓ Song gelernt: **{artist} — {title}** ({result['total_seconds']}s)",
        f"  BPM={feat['bpm']} | Key={feat['key']} | Dauer={feat['duration_s']}s",
        f"  Helligkeit: {feat['spectral_centroid_mean']} Hz | RMS: {feat['rms_mean']}",
        f"  Sektions-Grenzen (s): {feat['section_times_s']}",
        f"  Tags: {', '.join(meta['mb_tags'][:5]) or '(keine)'}",
    ]
    if meta.get("ab_bpm"):
        lines.append(f"  AcousticBrainz: BPM={round(float(meta['ab_bpm']),1)} Genre={meta.get('ab_genre','?')}")
    if result.get("midi"):
        lines.append(f"  MIDI: {result['midi']}")
    lines.append(f"  → Neo4j: (:Song {{name:'{title}', artist:'{artist}'}})")
    return "\n".join(lines)
