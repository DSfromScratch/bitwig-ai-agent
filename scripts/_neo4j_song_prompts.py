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


# ── Ground-Truth-Strategy-A aus note_plan ────────────────────────────────────

def build_ground_truth_pairs_from_songs(
    songs: list[dict[str, Any]] | None = None,
    max_pairs_per_song: int = 3,
) -> list[tuple[str, str]]:
    """Konvertiert (:Song.note_plan)-Strings in (user_prompt, ground_truth_json)-Paare
    für DPO Strategy A (deterministische Ground-Truth).

    Pro Track im note_plan wird ein Prompt erzeugt:
        prompt: "Schreibe den Bass-Part aus Under Pressure von Queen
                 (D major, 117 BPM) als MIDI-Pattern."
        answer: {"tool": "write_pattern_raw",
                 "args": {"notes": [...], "length_beats": 8, "instrument": "FM-4", ...}}

    Returns: Liste von (prompt, answer_json_string)-Tupeln, ready für
             _strategy_A_ground_truth() in generate_dpo_pairs.py.
    """
    import json as _json
    from scripts._note_plan_parser import parse_note_plan, to_write_pattern_raw_call

    if songs is None:
        songs = fetch_song_anchors(limit=100)

    pairs: list[tuple[str, str]] = []
    for song in songs:
        plan = song.get("note_plan")
        if not plan:
            continue
        parsed = parse_note_plan(plan)
        title = song.get("title") or "?"
        artist = song.get("artist") or "?"
        key = parsed.get("key") or song.get("key") or "C minor"
        bpm = parsed.get("bpm") or _safe_int_bpm(song.get("bpm"))

        for track in parsed["tracks"][:max_pairs_per_song]:
            if not track.get("notes"):
                continue
            call = to_write_pattern_raw_call(track, track_index=0, bpm=bpm, key=key)
            if not call:
                continue
            role = track.get("role") or "Track"
            instrument = track.get("instrument") or "Synth"
            prompt = (
                f"Schreibe den {role}-Part aus {title} von {artist} "
                f"({key}, {bpm} BPM) als exaktes MIDI-Pattern für {instrument}. "
                f"Nutze write_pattern_raw mit den originalen Noten."
            )
            pairs.append((prompt, _json.dumps(call, ensure_ascii=False)))

    log.info("Ground-Truth-Pairs aus note_plan: %d", len(pairs))
    return pairs


# ── Genre-Pattern Ground-Truth (Freesound-Onset-Skelett → Drum-Pattern) ──────

# GM-Drum-Pitches (vgl. DrumSound-Nodes in Neo4j)
_KICK, _SNARE, _CHAT, _OHAT = 36, 38, 42, 46


def fetch_genre_patterns(limit: int = 100) -> list[dict[str, Any]]:
    """Lädt GenrePattern-Knoten (aus Freesound/YouTube-Audio-Analyse) aus Neo4j.

    Liefert pro Genre: name, bpm_avg, typical_keys, energy, onset_steps.
    Leere Liste wenn Neo4j down."""
    try:
        from src.knowledge.neo4j_graph import is_available, session
    except Exception as exc:
        log.warning("Neo4j-Import fehlgeschlagen: %s", exc)
        return []
    if not is_available():
        log.warning("Neo4j nicht erreichbar — GenrePatterns übersprungen")
        return []

    rows: list[dict[str, Any]] = []
    with session() as s:
        result = s.run(
            """
            MATCH (g:GenrePattern)
            RETURN g.name         AS name,
                   g.bpm_avg      AS bpm,
                   g.typical_keys AS keys,
                   g.energy       AS energy,
                   g.onset_steps  AS onset_steps
            ORDER BY g.analyzed_at DESC
            LIMIT $limit
            """,
            limit=limit,
        )
        for r in result:
            d = dict(r)
            if not d.get("onset_steps"):
                continue
            rows.append(d)
    log.info("Neo4j: %d GenrePatterns geladen", len(rows))
    return rows


def _clean_onsets(onset_steps: list[int], steps_per_bar: int = 16) -> list[int]:
    """Bereinigt Onset-Steps: clamp auf [0, steps_per_bar-1], dedup, sortiert."""
    out = sorted({
        int(s) for s in onset_steps
        if isinstance(s, (int, float)) and 0 <= int(s) < steps_per_bar
    })
    return out


def drum_notes_from_onsets(
    onset_steps: list[int],
    energy: float = 0.6,
    steps_per_bar: int = 16,
    step_beats: float = 0.25,
) -> list[dict[str, Any]]:
    """Wandelt ein (Freesound-)Onset-Skelett in ein FINITES Kick/Snare/HiHat-
    Drum-Pattern (1 Takt) um.

    Musikalische Regeln (garantieren Terminierung + Spielbarkeit):
      * Kick  (36): On-Beat-Onsets ∩ {0,2,8,10}, immer mind. {0,8} (4/4-Fundament)
      * Snare (38): fester Backbeat {4,12}
      * HiHat (42): restliche Onset-Steps + 8tel-Grid, gedeckelt nach Energie

    Returns: Liste von {"pitch","start","dur","vel"} (start/dur in Beats).
    """
    onsets = _clean_onsets(onset_steps, steps_per_bar)

    # Kick: On-Beat-Onsets, Fundament {0,8} immer dabei
    kick_steps = sorted({0, 8} | {s for s in onsets if s in (0, 2, 8, 10)})

    # Snare: Standard-Backbeat
    snare_steps = [4, 12]

    # HiHat: Onsets, die nicht schon Kick/Snare sind, plus 8tel-Grundgerüst
    hat_cap = 4 + int(round(energy * 8))          # energy 0→4, 1→12 Hats
    used = set(kick_steps) | set(snare_steps)
    hat_candidates = sorted(
        (set(onsets) - used) | {s for s in range(0, steps_per_bar, 2)}
    )
    hat_steps = hat_candidates[:hat_cap]

    notes: list[dict[str, Any]] = []
    for st in kick_steps:
        notes.append({"pitch": _KICK, "start": round(st * step_beats, 4),
                      "dur": round(step_beats, 4), "vel": 0.9})
    for st in snare_steps:
        notes.append({"pitch": _SNARE, "start": round(st * step_beats, 4),
                      "dur": round(step_beats, 4), "vel": 0.8})
    for st in hat_steps:
        notes.append({"pitch": _CHAT, "start": round(st * step_beats, 4),
                      "dur": round(step_beats, 4), "vel": 0.5})

    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    return notes


_GENRE_DRUM_TEMPLATES = [
    "Schreibe ein {genre} Drum-Pattern ({bpm} BPM, 1 Takt) mit Kick, Snare und "
    "HiHat. Nutze write_pattern_raw mit den exakten Noten.",
    "Erzeuge einen 1-Takt {genre}-Groove bei {bpm} BPM (Kick/Snare/HiHat). "
    "Nutze write_pattern_raw.",
    "Komponiere ein typisches {genre} Schlagzeug-Pattern, {bpm} BPM, 4 Beats. "
    "Nutze write_pattern_raw.",
]


def build_genre_groundtruth_pairs(
    genres: list[dict[str, Any]] | None = None,
    max_per_genre: int = 1,
    seed: int | None = None,
) -> list[tuple[str, str]]:
    """Konvertiert GenrePattern-Onset-Skelette (Freesound) in DPO-Strategy-A
    Ground-Truth-Paare: (prompt, write_pattern_raw-json).

    Jedes Genre → finites, terminiertes Drum-Pattern (das Gegenmittel zum
    Runaway-Pattern-Problem). Drums sind atonal → KEIN key-Arg (hält
    key_conformance neutral=1.0 → hoher GT-Score).

    Returns: Liste von (prompt, answer_json_string)-Tupeln.
    """
    import json as _json

    rng = _seed_rng(seed)
    if genres is None:
        genres = fetch_genre_patterns(limit=100)

    pairs: list[tuple[str, str]] = []
    for g in genres:
        onset_steps = g.get("onset_steps") or []
        notes = drum_notes_from_onsets(
            onset_steps, energy=float(g.get("energy") or 0.6))
        if not notes:
            continue
        name = g.get("name") or "Genre"
        bpm = _safe_int_bpm(g.get("bpm"))
        call = {
            "tool": "write_pattern_raw",
            "args": {
                "track_index":  0,
                "notes":        notes,
                "length_beats": 4.0,
                "instrument":   "Drum Machine",
                "bpm":          bpm,
                "genre":        name,
            },
        }
        for _ in range(max_per_genre):
            template = rng.choice(_GENRE_DRUM_TEMPLATES)
            prompt = template.format(genre=name, bpm=bpm)
            pairs.append((prompt, _json.dumps(call, ensure_ascii=False)))

    log.info("Genre-Ground-Truth-Pairs (Freesound): %d", len(pairs))
    return pairs
