"""
Helper: zieht Songs aus Neo4j und baut daraus realistische Trainings-Prompts
für DPO/SFT.

Nutzt die (:Song)-Knoten (sowohl seed/training_data als auch via
learn_song_from_youtube ingestierte) als stilistische Anker:

  → "Schreibe ein Pattern im Stil von <Artist> - <Song> ..."
  → mit Constraint-Informationen aus den Audio-Features (BPM, Key, Tags)

Verwendet von:
  - scripts/generate_dpo_pairs.py  (DPO-Prompt-Quelle)
  - scripts/rl_train_loop.py       (Live-RL-Prompts)
  - scripts/extract_dpo_from_attempts.py (kontextuelle Anreicherung)
"""
from __future__ import annotations

import json
import logging
import random
from typing import Any

log = logging.getLogger(__name__)


def _seed_rng(seed: int | None) -> random.Random:
    return random.Random(seed) if seed is not None else random.Random()


def fetch_song_anchors(limit: int = 40, min_bpm: int = 60,
                       max_bpm: int = 200) -> list[dict[str, Any]]:
    """Lädt Song-Anker aus Neo4j. Liefert leere Liste wenn Neo4j down ist."""
    try:
        from src.knowledge.neo4j_graph import is_available, session
    except Exception as exc:
        log.warning("Neo4j-Import fehlgeschlagen: %s", exc)
        return []

    if not is_available():
        log.warning("Neo4j nicht erreichbar — Song-Anker werden übersprungen")
        return []

    rows: list[dict[str, Any]] = []
    with session() as s:
        result = s.run(
            """
            MATCH (sg:Song)
            OPTIONAL MATCH (sg)-[:BY]->(a:Artist)
            RETURN sg.name             AS title,
                   coalesce(a.name, sg.artist) AS artist,
                   sg.bpm              AS bpm,
                   sg.key              AS key,
                   sg.source           AS source,
                   sg.note_plan        AS note_plan,
                   sg.chord_progression AS chords,
                   sg.metadata_json    AS metadata_json
            ORDER BY sg.updated_at DESC
            LIMIT $limit
            """,
            limit=limit,
        )
        for r in result:
            d = dict(r)
            if d.get("bpm") and not (min_bpm <= float(d["bpm"]) <= max_bpm):
                continue
            if d.get("metadata_json"):
                try:
                    d["metadata"] = json.loads(d["metadata_json"])
                except Exception:
                    d["metadata"] = {}
            else:
                d["metadata"] = {}
            rows.append(d)
    log.info("Neo4j: %d Song-Anker geladen", len(rows))
    return rows


# ── Prompt-Templates ────────────────────────────────────────────────────────

_PATTERN_TEMPLATES = [
    "Schreibe ein {bars}-Takt Pattern für {track_name} im Stil von "
    "{artist} - {title} ({bpm} BPM, {key}).",
    "{artist} - {title}: erzeuge ein typisches {bars}-Takt {role} in {key}.",
    "Komponiere {bars} Takte {role}, inspiriert von {artist}s {title} "
    "(Tempo {bpm} BPM, Tonart {key}).",
    "Mach ein Pattern wie der {role}-Part in {title} von {artist} "
    "({bars} Takte, {key}, {bpm} BPM).",
]

_TRACK_ROLES = [
    ("Drums", "Drum-Pattern"),
    ("Bass", "Bassline"),
    ("Synth", "Lead-Synth"),
    ("Pad", "Pad/Flächen"),
    ("Arp", "Arpeggio"),
]


def _format_key(raw: str | None) -> str:
    if not raw:
        return "C minor"
    k = str(raw).strip()
    if "minor" in k.lower() or "major" in k.lower():
        return k
    return f"{k} minor"


def _safe_int_bpm(raw: Any, default: int = 120) -> int:
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return default


def build_prompts_from_songs(
    songs: list[dict[str, Any]],
    n_per_song: int = 3,
    bars_choices: tuple[int, ...] = (2, 4, 8),
    seed: int | None = None,
) -> list[str]:
    """Erzeugt User-Prompts aus Song-Ankern. Jeder Song bekommt n_per_song
    Varianten (verschiedene Rollen + Bars)."""
    rng = _seed_rng(seed)
    prompts: list[str] = []
    for song in songs:
        artist = song.get("artist") or "Unknown Artist"
        title = song.get("title") or "Unknown Track"
        bpm = _safe_int_bpm(song.get("bpm"))
        key = _format_key(song.get("key"))

        for _ in range(n_per_song):
            track_name, role = rng.choice(_TRACK_ROLES)
            template = rng.choice(_PATTERN_TEMPLATES)
            bars = rng.choice(bars_choices)
            prompts.append(template.format(
                bars=bars, track_name=track_name, role=role,
                artist=artist, title=title, bpm=bpm, key=key,
            ))
    return prompts


def build_constraint_dicts(
    songs: list[dict[str, Any]],
    n_per_song: int = 2,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Liefert maschinenlesbare Constraint-Dicts pro Song — als Basis für
    direkte write_pattern-Aufrufe (z.B. für Strategy-A Ground-Truth ohne
    LLM-Generierung)."""
    rng = _seed_rng(seed)
    out: list[dict[str, Any]] = []
    for song in songs:
        for _ in range(n_per_song):
            track_name, role = rng.choice(_TRACK_ROLES)
            bars = rng.choice((2, 4, 8))
            out.append({
                "artist": song.get("artist"),
                "title": song.get("title"),
                "track_name": track_name,
                "role": role,
                "bars": bars,
                "bpm": _safe_int_bpm(song.get("bpm")),
                "key": _format_key(song.get("key")),
                "source": song.get("source"),
                "tags": (song.get("metadata") or {}).get("musicbrainz_tags", []),
            })
    return out


def load_prompts(limit: int = 40, n_per_song: int = 3,
                 seed: int | None = None) -> list[str]:
    """Top-Level Convenience: lädt Anker + baut Prompts in einem Schritt."""
    songs = fetch_song_anchors(limit=limit)
    if not songs:
        return []
    return build_prompts_from_songs(songs, n_per_song=n_per_song, seed=seed)
