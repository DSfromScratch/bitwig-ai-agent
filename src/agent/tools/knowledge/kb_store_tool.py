"""
store_result_in_kb() — Speichert bewertete Artist/Song-Ergebnisse dauerhaft in Neo4j.

Flywheel:
  web_search() → gutes Ergebnis → store_result_in_kb()
  → nächste Anfrage → query_knowledge() findet es direkt (kein Web nötig)
  → generate_context_pairs.py erzeugt daraus neue Trainingspaare

Qualitätsbewertung (automatisch, Minimum 0.5 zum Speichern):
  BPM vorhanden          +0.25
  Key vorhanden          +0.25
  Chord/Pattern          +0.25
  Note-Plan vorhanden    +0.25
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langchain_core.tools import tool

log = logging.getLogger(__name__)

_INDEXES_CREATED = False


def _ensure_indexes() -> None:
    global _INDEXES_CREATED
    if _INDEXES_CREATED:
        return
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
        with neo4j_session() as s:
            s.run("""
                CREATE CONSTRAINT artist_name_unique IF NOT EXISTS
                FOR (a:Artist) REQUIRE a.name IS UNIQUE
            """)
            s.run("""
                CREATE CONSTRAINT song_unique IF NOT EXISTS
                FOR (s:Song) REQUIRE (s.name, s.artist) IS UNIQUE
            """)
            s.run("""
                CREATE VECTOR INDEX artist_embedding IF NOT EXISTS
                FOR (n:Artist) ON (n.embedding)
                OPTIONS {indexConfig: {`vector.dimensions`: 768,
                                       `vector.similarity_function`: 'cosine'}}
            """)
            s.run("""
                CREATE VECTOR INDEX song_embedding IF NOT EXISTS
                FOR (n:Song) ON (n.embedding)
                OPTIONS {indexConfig: {`vector.dimensions`: 768,
                                       `vector.similarity_function`: 'cosine'}}
            """)
        _INDEXES_CREATED = True
    except Exception as e:
        log.warning("Index-Erstellung: %s", e)


def _quality_score(data: dict) -> float:
    score = 0.0
    if data.get("bpm"):
        score += 0.25
    if data.get("key"):
        score += 0.25
    if data.get("chord_progression") or data.get("drum_pattern") or data.get("style"):
        score += 0.25
    if data.get("note_plan"):
        score += 0.25
    return round(score, 2)


def _embed(text: str) -> list[float] | None:
    try:
        from src.knowledge.store import get_embeddings
        return get_embeddings().embed_query(text)
    except Exception as e:
        log.warning("Embedding fehlgeschlagen: %s", e)
        return None


def _store_artist(s, data: dict, quality: float) -> str:
    name    = data["name"]
    devices = data.get("devices", [])
    devices_json = json.dumps(devices if isinstance(devices, list) else [devices], ensure_ascii=False)

    content = (
        f"Künstler: {name} | Genre: {data.get('genre','')} | "
        f"BPM: {data.get('bpm','')} | Tonart: {data.get('key','')} | "
        f"Stil: {data.get('style','')} | "
        f"Devices: {', '.join(devices) if isinstance(devices, list) else devices} | "
        f"Notenplan: {data.get('note_plan','')}"
    )
    emb = _embed(content)

    now = datetime.now(timezone.utc).isoformat()
    s.run("""
        MERGE (a:Artist {name: $name})
        SET a.genre         = $genre,
            a.bpm           = $bpm,
            a.key           = $key,
            a.style         = $style,
            a.devices_json  = $devices_json,
            a.note_plan     = $note_plan,
            a.quality_score = $quality,
            a.content       = $content,
            a.source        = $source,
            a.updated_at    = $now
    """, name=name, genre=data.get("genre",""), bpm=str(data.get("bpm","")),
         key=data.get("key",""), style=data.get("style",""),
         devices_json=devices_json, note_plan=data.get("note_plan",""),
         quality=quality, content=content, source=data.get("source","web_search"),
         now=now)

    if emb:
        s.run("MATCH (a:Artist {name: $name}) SET a.embedding = $emb",
              name=name, emb=emb)

    # Genre-Verknüpfung wenn Genre-Node existiert
    genre_name = data.get("genre", "").split("/")[0].strip()
    if genre_name:
        s.run("""
            MATCH (a:Artist {name: $name})
            MATCH (g:Genre) WHERE toLower(g.name) = toLower($genre)
            MERGE (a)-[:ASSOCIATED_WITH]->(g)
        """, name=name, genre=genre_name)

    return f"✓ Artist '{name}' gespeichert (Score: {quality:.2f}, Genre: {data.get('genre','')})"


def _store_song(s, data: dict, quality: float) -> str:
    name   = data["name"]
    artist = data.get("artist", "")

    content = (
        f"Song: {name} | Künstler: {artist} | "
        f"BPM: {data.get('bpm','')} | Tonart: {data.get('key','')} | "
        f"Akkorde: {data.get('chord_progression','')} | "
        f"Notenplan: {data.get('note_plan','')}"
    )
    emb = _embed(content)

    now = datetime.now(timezone.utc).isoformat()
    s.run("""
        MERGE (s:Song {name: $name, artist: $artist})
        SET s.bpm               = $bpm,
            s.key               = $key,
            s.chord_progression = $chords,
            s.note_plan         = $note_plan,
            s.quality_score     = $quality,
            s.content           = $content,
            s.source            = $source,
            s.updated_at        = $now
    """, name=name, artist=artist, bpm=str(data.get("bpm","")),
         key=data.get("key",""), chords=data.get("chord_progression",""),
         note_plan=data.get("note_plan",""), quality=quality,
         content=content, source=data.get("source","web_search"), now=now)

    if emb:
        s.run("MATCH (s:Song {name: $name, artist: $artist}) SET s.embedding = $emb",
              name=name, artist=artist, emb=emb)

    # Künstler-Verknüpfung wenn Artist-Node existiert
    if artist:
        s.run("""
            MATCH (s:Song {name: $name, artist: $artist})
            MERGE (a:Artist {name: $artist})
            MERGE (s)-[:BY]->(a)
        """, name=name, artist=artist)

    return f"✓ Song '{name}' von {artist} gespeichert (Score: {quality:.2f})"


@tool
def store_result_in_kb(data: dict) -> str:
    """Speichert bewertete Artist- oder Song-Ergebnisse dauerhaft in Neo4j.

    Nutze dieses Tool nachdem du web_search aufgerufen hast
    und ein vollständiges Ergebnis (BPM, Tonart, Akkorde/Pattern, Notenplan) vorliegt.
    Das gespeicherte Wissen steht beim nächsten Mal direkt via query_knowledge bereit.

    Mindest-Qualität zum Speichern: 0.5 (BPM + Key vorhanden).
    Bei Score < 0.5 wird NICHT gespeichert und eine Warnung zurückgegeben.

    Für Künstler (type='artist'):
      data = {
        "type": "artist",
        "name": "Aphex Twin",
        "genre": "IDM",
        "bpm": "120-160",
        "key": "A minor",
        "style": "Experimental, glitchig, Polyrhythmen...",
        "devices": ["FM-4", "Phase-4", "Polymer"],
        "note_plan": "Kick=[s0,s2,s5], Bass=A2...",
        "source": "web_search: Aphex Twin production"
      }

    Für Songs (type='song'):
      data = {
        "type": "song",
        "name": "Under Pressure",
        "artist": "Queen",
        "bpm": 117,
        "key": "D major",
        "chord_progression": "D-G-A-D",
        "note_plan": "Bass: D3=62 [s0,dur1]...",
        "source": "web_search"
      }
    """
    _ensure_indexes()

    entry_type = str(data.get("type", "artist")).lower()
    name = data.get("name", "").strip()

    if not name:
        return "⚠ Kein Name angegeben — nicht gespeichert."

    quality = _quality_score(data)
    if quality < 0.5:
        missing = []
        if not data.get("bpm"):      missing.append("BPM")
        if not data.get("key"):      missing.append("Tonart")
        if not (data.get("chord_progression") or data.get("style")): missing.append("Akkorde/Stil")
        if not data.get("note_plan"): missing.append("Notenplan")
        return (f"⚠ Qualitäts-Score {quality:.2f} zu niedrig — nicht gespeichert. "
                f"Fehlende Felder: {', '.join(missing)}")

    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
        with neo4j_session() as s:
            if entry_type == "song":
                if not data.get("artist"):
                    return "⚠ Song ohne Künstler — bitte 'artist' angeben."
                return _store_song(s, data, quality)
            else:
                return _store_artist(s, data, quality)
    except Exception as e:
        log.error("store_result_in_kb Fehler: %s", e)
        return f"✗ Fehler beim Speichern: {e}"
