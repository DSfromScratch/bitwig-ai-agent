"""
Audio-Beispiel-Suche: Freesound (primär) → YouTube-Fallback + librosa-Analyse.

Workflow:
  1. Freesound API (wenn FREESOUND_API_KEY gesetzt) → isolierte Loops, höhere Qualität
  2. Fallback: yt-dlp YouTube-Suche → kein API-Key nötig
  → 30s Snippet → BPM/Key/Onset via librosa → Neo4j-Cache
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

import httpx
import numpy as np
from langchain_core.tools import tool

FREESOUND_API_BASE = "https://freesound.org/apiv2"

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])


def _detect_key(chroma_mean: np.ndarray) -> str:
    """Krumhansl–Kessler Tonart-Erkennung."""
    best_score = -np.inf
    best_key = "C major"
    for i in range(12):
        rotated = np.roll(chroma_mean, -i)
        maj = float(np.corrcoef(rotated, MAJOR_PROFILE)[0, 1])
        mni = float(np.corrcoef(rotated, MINOR_PROFILE)[0, 1])
        if maj > best_score:
            best_score, best_key = maj, f"{NOTE_NAMES[i]} major"
        if mni > best_score:
            best_score, best_key = mni, f"{NOTE_NAMES[i]} minor"
    return best_key


def _freesound_search(query: str, max_results: int = 4) -> list[dict]:
    """Sucht Freesound.org nach Loops/Samples (benötigt FREESOUND_API_KEY)."""
    api_key = os.getenv("FREESOUND_API_KEY", "")
    if not api_key:
        return []
    try:
        resp = httpx.get(
            f"{FREESOUND_API_BASE}/search/text/",
            params={
                "query": query,
                "fields": "id,name,previews,duration,tags,avg_rating",
                "filter": "duration:[2 TO 60]",
                "sort": "rating_desc",
                "page_size": max_results,
                "token": api_key,
            },
            timeout=12,
        )
        if resp.status_code != 200:
            return []
        results = resp.json().get("results", [])
        return [
            {
                "title": r.get("name", ""),
                "duration": float(r.get("duration") or 30),
                "preview_url": (r.get("previews") or {}).get("preview-hq-mp3")
                               or (r.get("previews") or {}).get("preview-lq-mp3"),
                "tags": r.get("tags", [])[:5],
                "source": "freesound",
            }
            for r in results
            if r.get("previews")
        ]
    except Exception:
        return []


def _freesound_download(preview_url: str) -> str | None:
    """Lädt Freesound-Preview als MP3 in Temp-Datei."""
    try:
        resp = httpx.get(preview_url, timeout=25, follow_redirects=True)
        if resp.status_code != 200:
            return None
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(resp.content)
            return f.name
    except Exception:
        return None


def _youtube_search(query: str, max_results: int = 3) -> list[dict]:
    """Sucht YouTube ohne API-Key via yt-dlp ytsearch."""
    try:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
            entries = info.get("entries") or []
            return [
                {
                    "id": e.get("id"),
                    "title": e.get("title", ""),
                    "duration": e.get("duration", 0),
                    "url": f"https://www.youtube.com/watch?v={e.get('id')}",
                }
                for e in entries
                if e.get("id")
            ]
    except Exception:
        return []


def _download_snippet(url: str, duration: int = 30) -> str | None:
    """Lädt die ersten `duration` Sekunden als MP3 in eine Temp-Datei."""
    try:
        import yt_dlp
        tmp_dir = tempfile.mkdtemp()
        out_template = os.path.join(tmp_dir, "snippet.%(ext)s")
        opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }
            ],
            # nur die ersten `duration` Sekunden
            "postprocessor_args": {"ffmpeg": ["-t", str(duration)]},
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        mp3_path = os.path.join(tmp_dir, "snippet.mp3")
        if os.path.exists(mp3_path):
            return mp3_path
        # yt-dlp kann auch .webm o.ä. liefern — suche erste Audiodatei
        for f in os.listdir(tmp_dir):
            return os.path.join(tmp_dir, f)
        return None
    except Exception:
        return None


def _analyze_file(path: str, max_duration: float = 30.0) -> dict[str, Any]:
    """Analysiert Audio-Datei: BPM, Tonart, Energie, Onset-Steps."""
    import librosa  # lazy: schwere Dependency nur bei tatsächlicher Analyse

    y, sr = librosa.load(path, duration=max_duration, mono=True)

    # BPM — librosa gibt je nach Version Scalar oder 0-d/1-d Array zurück
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.round(float(np.atleast_1d(tempo)[0]), 1))

    # Tonart
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key = _detect_key(chroma.mean(axis=1))

    # Energie
    rms = float(librosa.feature.rms(y=y).mean())
    energy = round(min(1.0, rms * 20), 2)

    # Onset-Steps: erste 2 Takte auf 16 Steps quantisiert
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units="frames",
                                               backtrack=True, delta=0.07)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    beat_dur = 60.0 / bpm if bpm > 10 else 0.5
    bar_dur = beat_dur * 4

    bar1 = onset_times[onset_times < bar_dur]
    bar2 = onset_times[(onset_times >= bar_dur) & (onset_times < bar_dur * 2)]

    steps1 = sorted(set(min(15, int(t / bar_dur * 16)) for t in bar1))
    steps2 = sorted(set(min(15, int((t - bar_dur) / bar_dur * 16)) for t in bar2))

    return {"bpm": bpm, "key": key, "energy": energy,
            "steps_bar1": steps1, "steps_bar2": steps2}


def _genre_name_from_query(query: str) -> str:
    """Extrahiert den Genre-Namen aus einer Suchanfrage (erstes 1-2 Wörter)."""
    stop = {"drum", "loop", "beat", "sample", "pattern", "music", "style",
            "bpm", "hz", "free", "instrumental", "version"}
    words = query.lower().split()
    name_words = [w for w in words[:4] if w not in stop and not w.isdigit()]
    return " ".join(name_words[:2]).title() if name_words else query[:20].title()


def _format_record(record: "GenrePatternRecord", source: str = "Neo4j") -> str:  # noqa: F821
    """Formatiert einen GenrePatternRecord als lesbaren String."""
    bpm = record.bpm_avg
    keys = record.typical_keys
    steps = record.onset_steps
    grid = "".join("X" if i in steps else "." for i in range(16))
    lines = [
        f"**{record.name}** *(aus {source})*",
        f"  BPM: {bpm}  |  Tonart: {keys[0] if keys else '?'}  |  Energie: {record.energy}",
        f"  Takt 1: {grid}",
        f"  Quellen: {', '.join(record.sources[:2])}" if record.sources else "",
        "",
        "**→ Audio-Analyse:**",
        f"  BPM:          {int(round(bpm))}",
        f"  Tonart:       {keys[0] if keys else '?'}",
        f"  Energie:      {record.energy}",
        f"  Onset-Steps:  {steps}",
    ]
    return "\n".join(l for l in lines if l is not None)


@tool
def find_audio_example(query: str) -> str:
    """Sucht YouTube-Audio für ein Genre/Style und analysiert es mit librosa.

    Ergebnisse werden in Neo4j gespeichert — bei erneutem Aufruf desselben Genres
    kommt die Antwort sofort aus dem Cache (kein YouTube-Download nötig).

    Gibt BPM, Tonart, Energie und konkrete Onset-Steps zurück als Genre-Referenz.
    Kein API-Key nötig.

    Beispiele:
      find_audio_example("kuduro drum loop Angola 140 BPM")
      find_audio_example("dark techno kick pattern Berlin industrial")
      find_audio_example("UK garage 2step beat 130 BPM")
      find_audio_example("Burial atmospheric dubstep reverb pad loop")
    """
    from src.knowledge.repositories import GenrePatternRepository, GenrePatternRecord
    repo = GenrePatternRepository()

    # ── 1. Neo4j-Cache prüfen ──────────────────────────────────────────────────
    genre_name = _genre_name_from_query(query)
    cached = repo.find(genre_name)
    if cached:
        return f"**Audio-Analyse: '{query}'** (Cache)\n\n" + _format_record(cached, source="Neo4j-Cache")

    # Breitere Ähnlichkeitssuche als Fallback
    similar = repo.find_similar(query, limit=1)
    if similar and similar[0].name.lower() in query.lower():
        return f"**Audio-Analyse: '{query}'** (ähnlicher Cache-Eintrag)\n\n" + _format_record(similar[0], source="Neo4j")

    # ── 2. Freesound (primär) oder YouTube (Fallback) ─────────────────────────
    # Freesound: exakter Query — nur verwenden wenn genre-spezifische Treffer da sind
    # Kein generischer Fallback (würde falsche BPM liefern)
    fs_results = _freesound_search(query, max_results=4)
    use_freesound = bool(fs_results)
    source_label = "Freesound" if use_freesound else "YouTube"

    lines = [f"**Audio-Analyse: '{query}'** ({source_label})\n"]
    analyses: list[dict] = []

    if use_freesound:
        candidates = fs_results[:2]
        for item in candidates:
            title = item["title"]
            dur = item["duration"]
            lines.append(f"Lade: {title}")
            path = _freesound_download(item["preview_url"])
            if not path:
                lines.append("  ⚠️ Download fehlgeschlagen\n")
                continue
            try:
                analysis = _analyze_file(path, max_duration=min(30.0, dur))
                analysis["title"] = title
                analyses.append(analysis)
            except Exception as e:
                lines.append(f"  ⚠️ Analyse-Fehler: {e}\n")
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    else:
        videos = _youtube_search(query, max_results=3)
        if not videos:
            return f"Keine Ergebnisse für '{query}' (weder Freesound noch YouTube)."
        for video in videos[:2]:
            title = video["title"]
            url = video["url"]
            dur = video.get("duration") or 30
            lines.append(f"Lade: {title}")
            path = _download_snippet(url, duration=30)
            if not path:
                lines.append("  ⚠️ Download fehlgeschlagen\n")
                continue
            try:
                analysis = _analyze_file(path, max_duration=min(30.0, float(dur)))
                analysis["title"] = title
                analyses.append(analysis)
            except Exception as e:
                lines.append(f"  ⚠️ Analyse-Fehler: {e}\n")
            finally:
                try:
                    os.unlink(path)
                    os.rmdir(os.path.dirname(path))
                except OSError:
                    pass

    if not analyses:
        return "\n".join(lines) + "\nAudio-Analyse fehlgeschlagen."

    lines.append("")
    for a in analyses:
        bpm = a.get("bpm", 0)
        key = a.get("key", "?")
        energy = a.get("energy", 0)
        b1 = a.get("steps_bar1", [])
        b2 = a.get("steps_bar2", [])
        grid1 = "".join("X" if i in b1 else "." for i in range(16))
        grid2 = "".join("X" if i in b2 else "." for i in range(16))
        lines.append(f"**{a['title']}**")
        lines.append(f"  BPM: {bpm}  |  Tonart: {key}  |  Energie: {energy}")
        lines.append(f"  Takt 1: {grid1}")
        lines.append(f"  Takt 2: {grid2}")
        lines.append("")

    # ── 3. Konsens + in Neo4j speichern ───────────────────────────────────────
    bpms = [a["bpm"] for a in analyses if a.get("bpm", 0) > 10]
    keys = [a["key"] for a in analyses if a.get("key")]
    if bpms:
        avg_bpm = round(sum(bpms) / len(bpms), 1)
        bpm_range = [min(bpms), max(bpms)]
        ref = analyses[0]
        steps = ref.get("steps_bar1", [])
        energy = ref.get("energy", 0.5)

        record = GenrePatternRecord(
            name=genre_name,
            bpm_avg=avg_bpm,
            bpm_range=bpm_range,
            typical_keys=keys,
            energy=energy,
            onset_steps=steps,
            sources=[a["title"] for a in analyses],
            analyzed_at=__import__("datetime").date.today().isoformat(),
        )
        repo.save(record)
        lines.append(f"✓ Als GenrePattern '{genre_name}' in Neo4j gespeichert")
        lines.append("")
        lines.append("**→ Audio-Analyse:**")
        lines.append(f"  BPM:          {int(round(avg_bpm))}")
        lines.append(f"  Tonart:       {keys[0] if keys else '?'}")
        lines.append(f"  Energie:      {energy}")
        lines.append(f"  Onset-Steps:  {steps}")

    return "\n".join(lines)
