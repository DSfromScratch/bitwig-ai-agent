"""
Tool: get_artist_context

Gibt das musikalische Profil eines Künstlers aus der Wissensdatenbank zurück:
Stil, Genre, typische BPM/Tonart, charakteristische Devices, assoziierte Genres,
Referenz-Songs (via :BY) und klanglich ähnliche Songs (via :SIMILAR_TO).

Vor dem Komponieren „im Stil von X" aufrufen, um die stilistischen Merkmale
des Künstlers vollständig zu verstehen.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool


def _parse_devices(devices_json: str | None) -> list[str]:
    try:
        devs = json.loads(devices_json or "[]")
        return devs if isinstance(devs, list) else []
    except Exception:
        return []


@tool
def get_artist_context(artist_name: str) -> str:
    """Gibt das stilistische Profil eines Künstlers aus der Wissensdatenbank zurück.

    Zeigt: Stil-Beschreibung, Genre, typische BPM/Tonart, charakteristische
    Devices, assoziierte Genres, Referenz-Songs des Künstlers und klanglich
    ähnliche Songs aus der KB.

    Aufrufen, bevor „im Stil von <Künstler>" komponiert wird, um die
    stilistischen Merkmale (Sounds, Tempo, Harmonik) zu verstehen.

    Args:
        artist_name: Name des Künstlers (z.B. "Daft Punk", "Aphex Twin").
                     Teil-Treffer (case-insensitive) werden unterstützt.
    """
    try:
        from src.knowledge.neo4j_graph import is_available, session
        if not is_available():
            return "❌ Neo4j nicht erreichbar."
    except Exception as e:
        return f"❌ Neo4j-Fehler: {e}"

    name = (artist_name or "").strip()
    if not name:
        return "❌ Bitte einen Künstlernamen angeben."

    with session() as s:
        artist = s.run("""
            MATCH (a:Artist)
            WHERE toLower(a.name) = toLower($name)
               OR toLower(a.name) CONTAINS toLower($name)
               OR toLower($name) CONTAINS toLower(a.name)
            RETURN a.name AS name, a.genre AS genre, a.style AS style,
                   a.bpm AS bpm, a.key AS key, a.devices_json AS devices_json,
                   a.note_plan AS note_plan, a.quality_score AS score
            ORDER BY CASE WHEN toLower(a.name) = toLower($name) THEN 0 ELSE 1 END,
                     coalesce(a.quality_score, 0) DESC
            LIMIT 1
        """, name=name).single()

        if not artist:
            available = s.run(
                "MATCH (a:Artist) RETURN a.name AS n ORDER BY n"
            ).data()
            names = ", ".join(r["n"] for r in available)
            return (f"❌ Kein Künstler '{name}' in der KB gefunden.\n"
                    f"Verfügbar: {names}")

        a_name = artist["name"]

        # Referenz-Songs des Künstlers (via :BY)
        songs = s.run("""
            MATCH (song:Song)-[:BY]->(a:Artist {name: $name})
            RETURN song.name AS name, song.bpm AS bpm, song.key AS key,
                   song.chord_progression AS chords
            ORDER BY song.name
        """, name=a_name).data()

        # Assoziierte Genres (via :ASSOCIATED_WITH)
        genres = s.run("""
            MATCH (a:Artist {name: $name})-[:ASSOCIATED_WITH]->(g:Genre)
            RETURN g.name AS name ORDER BY g.name
        """, name=a_name).data()

        # Klanglich ähnliche Songs (via :SIMILAR_TO ab Referenz-Songs, C.10)
        similar = s.run("""
            MATCH (song:Song)-[:BY]->(a:Artist {name: $name})
            MATCH (song)-[r:SIMILAR_TO]->(other:Song)
            OPTIONAL MATCH (other)-[:BY]->(oa:Artist)
            RETURN DISTINCT other.name AS song, oa.name AS artist,
                   round(r.score, 3) AS score
            ORDER BY score DESC LIMIT 5
        """, name=a_name).data()

    # ── Ausgabe formatieren ──────────────────────────────────────────────
    lines = [f"**Künstler: {a_name}**"]
    meta = []
    if artist.get("genre"):
        meta.append(f"Genre: {artist['genre']}")
    if artist.get("bpm"):
        meta.append(f"BPM: {artist['bpm']}")
    if artist.get("key"):
        meta.append(f"Tonart: {artist['key']}")
    if meta:
        lines.append("  " + " | ".join(meta))
    if artist.get("style"):
        lines.append(f"  Stil: {artist['style']}")

    devices = _parse_devices(artist.get("devices_json"))
    if devices:
        lines.append("  Typische Devices: " + ", ".join(devices[:8]))

    if genres:
        lines.append("  Assoziierte Genres: " + ", ".join(g["name"] for g in genres))

    if songs:
        song_strs = []
        for song in songs:
            extra = []
            if song.get("bpm"):
                extra.append(f"{song['bpm']} BPM")
            if song.get("key"):
                extra.append(song["key"])
            suffix = f" ({', '.join(extra)})" if extra else ""
            song_strs.append(f"{song['name']}{suffix}")
        lines.append("  Referenz-Songs: " + "; ".join(song_strs))

    if similar:
        sim_strs = [
            f"{r['song']}" + (f" – {r['artist']}" if r.get("artist") else "")
            + (f" ({r['score']})" if r.get("score") is not None else "")
            for r in similar
        ]
        lines.append("  Klanglich ähnlich: " + "; ".join(sim_strs))

    return "\n".join(lines)
