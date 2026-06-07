#!/usr/bin/env python3
"""Harvester: zieht Genre-Drum-Loops von Freesound, analysiert sie mit librosa
und speichert das Ergebnis als GenrePattern in Neo4j + als JSON-Dump.

Die so gewonnenen Genre-Daten (BPM / Key / Energy / Onset-Skelett) speisen das
DPO-Training: `build_genre_groundtruth_pairs()` baut daraus finite, terminierte
Drum-Ground-Truth (das Gegenmittel zum Runaway-Pattern-Problem).

Verlässlich aus Freesound: BPM (Konsens), Key (Krumhansl), Energy (RMS),
rhythmisches Onset-Skelett. Die exakte Instrument-Zuordnung (Kick/Snare/HiHat)
geschieht später regelbasiert in `drum_notes_from_onsets()`.

Usage:
    python -m scripts.harvest_freesound                 # alle kuratierten Genres
    python -m scripts.harvest_freesound --genres techno house dnb
    python -m scripts.harvest_freesound --per-genre 3 --dry-run
    FREESOUND_API_KEY muss in .env gesetzt sein.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("harvest_freesound")

# Kuratierte Genre-Queries: (Genre-Name, Freesound-Query, erwartete BPM-Range)
# Query zielt bewusst auf 1-Takt Drum-Loops mit Genre-Kontext.
CURATED_GENRES: list[tuple[str, str, tuple[int, int]]] = [
    ("Techno",      "techno loop",              (120, 145)),
    ("House",       "house drum loop",          (118, 130)),
    ("Deep House",  "deep house loop",          (118, 126)),
    ("Drum and Bass", "drum and bass break",    (160, 180)),
    ("Dubstep",     "dubstep drum loop",        (138, 145)),
    ("Hip Hop",     "hip hop boom bap drums",   (82, 96)),
    ("Trap",        "trap hi hat loop",         (130, 160)),
    ("Funk",        "funk drum break",          (95, 115)),
    ("Disco",       "disco drum loop",          (115, 128)),
    ("Breakbeat",   "amen break loop",          (130, 150)),
    ("Reggaeton",   "reggaeton dembow loop",    (88, 100)),
    ("Afrobeat",    "afrobeat drum loop",       (100, 120)),
]

OUT_JSON = Path("training_data/freesound_genres.json")


def _bpm_in_range(bpm: float, rng: tuple[int, int], tol: int = 8) -> bool:
    lo, hi = rng
    return (lo - tol) <= bpm <= (hi + tol)


def harvest_genre(
    name: str,
    query: str,
    bpm_range: tuple[int, int],
    per_genre: int = 3,
) -> dict[str, Any] | None:
    """Sucht + analysiert bis zu `per_genre` Loops für ein Genre, bildet Konsens."""
    from src.agent.tools.knowledge.freesound_tool import (
        _analyze_file,
        _freesound_download,
        _freesound_search,
    )

    results = _freesound_search(query, max_results=per_genre * 2)
    if not results:
        log.warning("  ⚠ keine Freesound-Treffer für '%s'", query)
        return None

    analyses: list[dict[str, Any]] = []
    for item in results:
        if len(analyses) >= per_genre:
            break
        dur = float(item.get("duration") or 30)
        path = _freesound_download(item["preview_url"])
        if not path:
            continue
        try:
            a = _analyze_file(path, max_duration=min(12.0, dur))
            a["title"] = item["title"]
            # BPM-Plausibilität: librosa oktaviert gern (halbe/doppelte/3/2 BPM)
            bpm = a["bpm"]
            for factor in (1.0, 2.0, 0.5, 1.5, 2.0 / 3.0, 3.0, 4.0 / 3.0):
                if _bpm_in_range(bpm * factor, bpm_range):
                    a["bpm"] = round(bpm * factor, 1)
                    break
            analyses.append(a)
            log.info("    ✓ %-42s bpm=%-5s key=%-8s steps=%s",
                     item["title"][:42], a["bpm"], a["key"], a["steps_bar1"])
        except Exception as exc:
            log.warning("    ⚠ Analyse-Fehler: %s", exc)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    if not analyses:
        return None

    bpms = [a["bpm"] for a in analyses if a.get("bpm", 0) > 10]
    keys = [a["key"] for a in analyses if a.get("key")]
    energies = [a.get("energy", 0.5) for a in analyses]
    # Onset-Skelett: vom Loop, dessen BPM am nächsten an der Genre-Mitte liegt
    mid = sum(bpm_range) / 2
    ref = min(analyses, key=lambda a: abs(a.get("bpm", 999) - mid))

    return {
        "name":         name,
        "query":        query,
        "bpm_avg":      round(sum(bpms) / len(bpms), 1) if bpms else mid,
        "bpm_range":    [min(bpms), max(bpms)] if bpms else list(bpm_range),
        "typical_keys": list(dict.fromkeys(keys))[:3],   # dedup, max 3
        "energy":       round(sum(energies) / len(energies), 2),
        "onset_steps":  ref.get("steps_bar1", []),
        "sources":      [a["title"] for a in analyses],
    }


def save_to_neo4j(record: dict[str, Any]) -> bool:
    """Speichert ein Genre-Record als GenrePattern-Node in Neo4j."""
    try:
        from src.knowledge.repositories import (
            GenrePatternRecord,
            GenrePatternRepository,
        )
        import datetime as _dt

        rec = GenrePatternRecord(
            name=record["name"],
            bpm_avg=record["bpm_avg"],
            bpm_range=record["bpm_range"],
            typical_keys=record["typical_keys"] or ["A minor"],
            energy=record["energy"],
            onset_steps=record["onset_steps"],
            sources=record["sources"],
            analyzed_at=_dt.date.today().isoformat(),
        )
        GenrePatternRepository().save(rec)
        return True
    except Exception as exc:
        log.warning("  ⚠ Neo4j-Save fehlgeschlagen für %s: %s", record["name"], exc)
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--genres", nargs="*", default=None,
                    help="Nur diese Genre-Namen harvesten (Default: alle kuratierten)")
    ap.add_argument("--per-genre", type=int, default=3,
                    help="Loops pro Genre analysieren (Konsens)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Nicht in Neo4j speichern, nur JSON-Dump")
    args = ap.parse_args(argv)

    if not os.getenv("FREESOUND_API_KEY"):
        log.error("FREESOUND_API_KEY nicht gesetzt (.env) — Abbruch.")
        return 2

    selected = CURATED_GENRES
    if args.genres:
        wanted = {g.lower() for g in args.genres}
        selected = [g for g in CURATED_GENRES if g[0].lower() in wanted]
        if not selected:
            log.error("Keine passenden Genres zu %s", args.genres)
            return 2

    records: list[dict[str, Any]] = []
    for name, query, bpm_range in selected:
        log.info("🎵 %s  ('%s')", name, query)
        rec = harvest_genre(name, query, bpm_range, per_genre=args.per_genre)
        if not rec:
            continue
        records.append(rec)
        if not args.dry_run and save_to_neo4j(rec):
            log.info("  💾 GenrePattern '%s' in Neo4j gespeichert", name)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    log.info("\n✅ %d Genres geharvestet → %s", len(records), OUT_JSON)
    return 0


if __name__ == "__main__":
    sys.exit(main())
