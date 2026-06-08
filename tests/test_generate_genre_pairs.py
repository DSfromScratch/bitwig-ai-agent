"""Tests für scripts/generate_genre_pairs.py — Noten-Dichte ≥ 8 pro Pair."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_genre_pairs.py"
_spec = importlib.util.spec_from_file_location("generate_genre_pairs", _SCRIPT)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


@pytest.fixture(scope="module")
def all_pairs():
    return gen.generate_pairs()


def _notes(p: dict) -> list[dict]:
    try:
        obj = json.loads(p["completion"])
        notes_raw = obj.get("args", {}).get("notes", obj.get("notes", "[]"))
        if isinstance(notes_raw, str):
            notes_raw = json.loads(notes_raw)
        return notes_raw if isinstance(notes_raw, list) else []
    except Exception:
        return []


# ── Basisstruktur ─────────────────────────────────────────────────────────────

def test_pairs_generated(all_pairs):
    assert len(all_pairs) >= 100


def test_required_keys(all_pairs):
    for p in all_pairs:
        assert "prompt" in p
        assert "completion" in p
        assert "source" in p


def test_completion_is_valid_json(all_pairs):
    for p in all_pairs:
        obj = json.loads(p["completion"])
        assert obj.get("tool") == "write_pattern"


# ── Noten-Dichte ──────────────────────────────────────────────────────────────

def test_bass_pairs_min_8_notes(all_pairs):
    """Bass-Pairs haben mindestens 8 Noten."""
    bass = [p for p in all_pairs if "/bass/" in p["source"]]
    assert bass, "Keine Bass-Pairs gefunden"
    for p in bass:
        n = len(_notes(p))
        assert n >= 8, f"Bass-Pair hat nur {n} Noten: {p['prompt']}"


def test_melody_pairs_min_8_notes(all_pairs):
    """Melodie-Pairs haben mindestens 8 Noten."""
    mel = [p for p in all_pairs if "/melody/" in p["source"]]
    assert mel, "Keine Melodie-Pairs gefunden"
    for p in mel:
        n = len(_notes(p))
        assert n >= 8, f"Melodie-Pair hat nur {n} Noten: {p['prompt']}"


def test_drum_pairs_not_empty(all_pairs):
    """Drum-Pairs (nicht Ambient) haben mindestens 1 Note."""
    drums = [p for p in all_pairs
             if "/drums/" in p["source"] and "Ambient" not in p["source"]]
    for p in drums:
        notes = _notes(p)
        assert len(notes) >= 1, f"Drum-Pair leer: {p['prompt']}"


def test_all_steps_in_bar(all_pairs):
    """Alle Noten liegen in Step 0–15."""
    for p in all_pairs:
        for n in _notes(p):
            assert 0 <= n["step"] <= 15, f"Step außerhalb Takt: {n['step']}"


def test_avg_notes_above_8(all_pairs):
    """Durchschnittliche Notenzahl aller Pairs ≥ 8."""
    counts = [len(_notes(p)) for p in all_pairs]
    avg = sum(counts) / len(counts) if counts else 0
    assert avg >= 8, f"Ø Noten zu gering: {avg:.1f}"


# ── Genres vollständig ────────────────────────────────────────────────────────

def test_all_genres_present(all_pairs):
    # Source-Format: "genre_translation/{genre}/drums/{section}"
    # Genre-Namen können Slashes enthalten → nur erstes Segment nach "genre_translation/" nehmen
    sources = set()
    for p in all_pairs:
        src = p["source"]
        if src.startswith("genre_translation/"):
            genre = src[len("genre_translation/"):].rsplit("/", 2)[0]
            sources.add(genre)
    for genre in gen.GENRES:
        assert genre in sources, f"Genre fehlt: {genre}"
