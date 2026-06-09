"""
Artist/Song-Metadaten-Suche für den Bitwig-Agenten.

Kombiniert kostenlose, lizenz-saubere Quellen:
- MusicBrainz (Open-Source-Musikdatenbank — MBID, Album, Release, Tags)
- Last.fm (Tags, ähnliche Künstler — `LASTFM_API_KEY` optional)
- AcousticBrainz (low-/high-level Audio-Features pro Recording — best-effort)

Liefert strukturierte Metadaten, **keine Audio-Files** — das übernimmt
`learn_song_from_youtube`. Damit kann der Agent vor dem Download wissen,
ob ein Song überhaupt Sinn ergibt (Genre, BPM-Erwartung, etc.).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()
log = logging.getLogger("bitwig-agent")

_USER_AGENT = "bitwig-ai-agent/1.0 (https://github.com/DSfromScratch/bitwig-ai-agent)"
_MB_BASE = "https://musicbrainz.org/ws/2"
_AB_BASE = "https://acousticbrainz.org/api/v1"
_LFM_BASE = "https://ws.audioscrobbler.com/2.0/"
_TIMEOUT = 8.0


def _musicbrainz_lookup(artist: str, title: str) -> dict[str, Any] | None:
    """Sucht das erste Recording-Match in MusicBrainz."""
    params = {
        "query": f'artist:"{artist}" AND recording:"{title}"',
        "fmt": "json",
        "limit": 3,
    }
    try:
        r = httpx.get(
            f"{_MB_BASE}/recording",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        recordings = r.json().get("recordings", [])
        if not recordings:
            return None
        rec = recordings[0]
        return {
            "mbid": rec.get("id"),
            "title": rec.get("title"),
            "artist": (rec.get("artist-credit") or [{}])[0].get("name", artist),
            "length_ms": rec.get("length"),
            "releases": [
                {"title": rel.get("title"), "date": rel.get("date")}
                for rel in (rec.get("releases") or [])[:3]
            ],
            "tags": [t["name"] for t in (rec.get("tags") or [])][:8],
            "score": rec.get("score"),
        }
    except Exception as exc:
        log.debug("MusicBrainz Fehler: %s", exc)
        return None


def _acousticbrainz_features(mbid: str) -> dict[str, Any] | None:
    """Holt Low-Level- + High-Level-Audio-Features falls vorhanden."""
    if not mbid:
        return None
    out: dict[str, Any] = {}
    try:
        low = httpx.get(
            f"{_AB_BASE}/{mbid}/low-level",
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
        if low.status_code == 200:
            data = low.json()
            rhythm = data.get("rhythm", {})
            tonal = data.get("tonal", {})
            out["bpm"] = rhythm.get("bpm")
            out["key"] = tonal.get("key_key")
            out["scale"] = tonal.get("key_scale")
            out["key_strength"] = tonal.get("key_strength")
    except Exception as exc:
        log.debug("AcousticBrainz low-level Fehler: %s", exc)

    try:
        high = httpx.get(
            f"{_AB_BASE}/{mbid}/high-level",
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
        if high.status_code == 200:
            hl = high.json().get("highlevel", {})
            for category in ("genre_dortmund", "genre_rosamerica",
                             "mood_happy", "mood_aggressive", "mood_relaxed",
                             "danceability", "voice_instrumental"):
                if category in hl:
                    out[category] = hl[category].get("value")
    except Exception as exc:
        log.debug("AcousticBrainz high-level Fehler: %s", exc)

    return out or None


def _lastfm_info(artist: str, title: str) -> dict[str, Any] | None:
    """Last.fm Tags + ähnliche Tracks (nur wenn API-Key gesetzt)."""
    api_key = os.getenv("LASTFM_API_KEY", "")
    if not api_key:
        return None
    try:
        r = httpx.get(
            _LFM_BASE,
            params={
                "method": "track.getInfo",
                "api_key": api_key,
                "artist": artist,
                "track": title,
                "format": "json",
                "autocorrect": 1,
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        track = r.json().get("track")
        if not track:
            return None
        return {
            "tags": [t["name"] for t in track.get("toptags", {}).get("tag", [])][:8],
            "playcount": track.get("playcount"),
            "listeners": track.get("listeners"),
            "url": track.get("url"),
        }
    except Exception as exc:
        log.debug("Last.fm Fehler: %s", exc)
        return None


def _format(data: dict[str, Any]) -> str:
    lines = [f"**Song-Metadaten:** {data.get('artist','?')} — {data.get('title','?')}"]

    mb = data.get("musicbrainz")
    if mb:
        lines.append(f"MBID: `{mb.get('mbid','-')}` (match score {mb.get('score','?')})")
        if mb.get("length_ms"):
            lines.append(f"Länge: {mb['length_ms'] // 1000}s")
        if mb.get("tags"):
            lines.append(f"MB-Tags: {', '.join(mb['tags'])}")
        if mb.get("releases"):
            rels = ", ".join(f"{r['title']} ({r.get('date','?')})" for r in mb["releases"])
            lines.append(f"Releases: {rels}")

    ab = data.get("acousticbrainz")
    if ab:
        if ab.get("bpm"):
            lines.append(f"BPM (AB): {round(float(ab['bpm']), 1)}")
        if ab.get("key"):
            lines.append(f"Tonart (AB): {ab['key']} {ab.get('scale','')}".strip())
        for cat in ("genre_dortmund", "genre_rosamerica", "mood_happy",
                    "mood_aggressive", "mood_relaxed", "danceability",
                    "voice_instrumental"):
            if cat in ab:
                lines.append(f"{cat}: {ab[cat]}")

    lf = data.get("lastfm")
    if lf:
        if lf.get("tags"):
            lines.append(f"Last.fm-Tags: {', '.join(lf['tags'])}")
        if lf.get("playcount"):
            lines.append(f"Plays: {lf['playcount']}, Listener: {lf.get('listeners','?')}")

    if not any([mb, ab, lf]):
        lines.append("(keine Metadaten gefunden — Schreibweise prüfen)")

    return "\n".join(lines)


def search_artist_song_dict(artist: str, title: str) -> dict[str, Any]:
    """Programmatische Variante — liefert dict statt str. Wird von learn_song_* genutzt."""
    mb = _musicbrainz_lookup(artist, title)
    ab = _acousticbrainz_features(mb["mbid"]) if mb else None
    lf = _lastfm_info(artist, title)
    return {
        "artist": artist,
        "title": title,
        "musicbrainz": mb,
        "acousticbrainz": ab,
        "lastfm": lf,
    }


@tool
def search_artist_song(artist: str, title: str) -> str:
    """Sucht Metadaten zu einem Song (Künstler + Titel) in öffentlichen Musikdatenbanken.

    Nutzt MusicBrainz (MBID, Album, Release, Tags), AcousticBrainz (BPM, Tonart,
    Genre, Mood — wenn der Song dort analysiert wurde) und optional Last.fm (Tags,
    wenn `LASTFM_API_KEY` gesetzt ist).

    KEIN Audio-Download — das macht `learn_song_from_youtube`.

    Args:
        artist: Künstler-Name (z.B. "Radiohead")
        title:  Song-Titel (z.B. "Idioteque")
    """
    data = search_artist_song_dict(artist, title)
    return _format(data)


@tool
def list_known_songs(limit: int = 20) -> str:
    """Listet die in der Neo4j-Wissensdatenbank gespeicherten Songs.

    Nutze dieses Tool bei Fragen wie "welche Songs kennst du?" oder
    "zeige mir bekannte/gelernte Songs". Es liefert vorhandene Song-Knoten
    inklusive Künstler, BPM, Tonart und Qualitäts-Score.
    """
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 20

    try:
        from src.knowledge.neo4j_graph import is_available, session
        if not is_available():
            return "Keine Songliste verfügbar: Neo4j ist nicht erreichbar."
    except Exception as exc:
        return f"Keine Songliste verfügbar: Neo4j-Fehler: {exc}"

    try:
        with session() as s:
            rows = s.run("""
                MATCH (song:Song)
                RETURN song.name AS name,
                       song.artist AS artist,
                       song.bpm AS bpm,
                       song.key AS key,
                       song.quality_score AS score
                ORDER BY coalesce(song.quality_score, 0) DESC,
                         toLower(coalesce(song.artist, '')),
                         toLower(song.name)
                LIMIT $limit
            """, limit=limit).data()
    except Exception as exc:
        return f"Keine Songliste verfügbar: Neo4j-Abfrage fehlgeschlagen: {exc}"

    if not rows:
        return "Keine Songs in der Wissensdatenbank gefunden."

    lines = [f"Bekannte Songs in der Wissensdatenbank ({len(rows)}):"]
    for row in rows:
        artist = row.get("artist") or "?"
        bpm = row.get("bpm")
        key = row.get("key") or "?"
        score = row.get("score")
        details = []
        if bpm:
            details.append(f"{round(float(bpm), 1)} BPM")
        if key != "?":
            details.append(f"Tonart {key}")
        if score is not None:
            details.append(f"Score {float(score):.2f}")
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"- {artist} — {row.get('name') or '?'}{suffix}")
    return "\n".join(lines)
