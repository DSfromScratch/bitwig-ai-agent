"""Tests für scripts/_neo4j_song_prompts.py — Neo4j-Anker als Trainings-Prompts."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


@patch("scripts._neo4j_song_prompts.logging")
def test_fetch_song_anchors_returns_empty_when_neo4j_down(_log):
    """Wenn is_available()=False, leise leere Liste zurückgeben."""
    with patch("src.knowledge.neo4j_graph.is_available", return_value=False):
        from scripts._neo4j_song_prompts import fetch_song_anchors
        assert fetch_song_anchors() == []


def test_fetch_song_anchors_parses_metadata_json():
    from scripts import _neo4j_song_prompts as mod

    sess = MagicMock()
    sess.run.return_value = iter([
        {"title": "Brittle Rille", "artist": "Kevin MacLeod", "bpm": 89.1,
         "key": "E", "source": "learn_song_from_youtube",
         "note_plan": None, "chords": None,
         "metadata_json": '{"musicbrainz_tags": ["ambient", "instrumental"]}'},
        {"title": "Idioteque", "artist": "Radiohead", "bpm": 137.5,
         "key": "A#", "source": "learn_song_from_youtube",
         "note_plan": None, "chords": None, "metadata_json": None},
    ])
    sess_ctx = MagicMock()
    sess_ctx.__enter__.return_value = sess

    with patch.object(mod, "is_available", return_value=True, create=True), \
         patch.object(mod, "session", return_value=sess_ctx, create=True):
        # mod.is_available wird via lokalen import gebunden — direkt patchen:
        with patch("src.knowledge.neo4j_graph.is_available", return_value=True), \
             patch("src.knowledge.neo4j_graph.session", return_value=sess_ctx):
            rows = mod.fetch_song_anchors(limit=10)

    assert len(rows) == 2
    assert rows[0]["metadata"]["musicbrainz_tags"] == ["ambient", "instrumental"]
    assert rows[1]["metadata"] == {}


def test_fetch_song_anchors_filters_bpm_range():
    from scripts import _neo4j_song_prompts as mod
    sess = MagicMock()
    sess.run.return_value = iter([
        {"title": "Slow", "artist": "X", "bpm": 40, "key": "C",
         "source": "x", "note_plan": None, "chords": None, "metadata_json": None},
        {"title": "Mid",  "artist": "Y", "bpm": 120, "key": "D",
         "source": "y", "note_plan": None, "chords": None, "metadata_json": None},
        {"title": "Fast", "artist": "Z", "bpm": 220, "key": "E",
         "source": "z", "note_plan": None, "chords": None, "metadata_json": None},
    ])
    sess_ctx = MagicMock()
    sess_ctx.__enter__.return_value = sess
    with patch("src.knowledge.neo4j_graph.is_available", return_value=True), \
         patch("src.knowledge.neo4j_graph.session", return_value=sess_ctx):
        rows = mod.fetch_song_anchors(limit=10, min_bpm=60, max_bpm=200)
    assert len(rows) == 1 and rows[0]["title"] == "Mid"


def test_format_key_appends_minor_when_missing():
    from scripts._neo4j_song_prompts import _format_key
    assert _format_key("E") == "E minor"
    assert _format_key("C major") == "C major"
    assert _format_key("A minor") == "A minor"
    assert _format_key(None) == "C minor"


def test_safe_int_bpm():
    from scripts._neo4j_song_prompts import _safe_int_bpm
    assert _safe_int_bpm(89.1) == 89
    assert _safe_int_bpm("128") == 128
    assert _safe_int_bpm(None) == 120
    assert _safe_int_bpm("garbage", default=140) == 140


def test_build_prompts_from_songs_is_deterministic_with_seed():
    from scripts._neo4j_song_prompts import build_prompts_from_songs
    songs = [
        {"title": "T1", "artist": "A1", "bpm": 120, "key": "C minor"},
        {"title": "T2", "artist": "A2", "bpm": 90,  "key": "D"},
    ]
    p1 = build_prompts_from_songs(songs, n_per_song=2, seed=42)
    p2 = build_prompts_from_songs(songs, n_per_song=2, seed=42)
    assert p1 == p2
    assert len(p1) == 4
    # Jeder Prompt referenziert echten Künstler + Song
    for prompt in p1:
        assert any(s["artist"] in prompt and s["title"] in prompt for s in songs)
        # BPM + Key müssen drin sein
        assert "BPM" in prompt or "Tempo" in prompt or "Takt" in prompt


def test_build_constraint_dicts_returns_machine_readable():
    from scripts._neo4j_song_prompts import build_constraint_dicts
    songs = [{"title": "T", "artist": "A", "bpm": 130, "key": "F minor",
              "source": "seed", "metadata": {"musicbrainz_tags": ["techno"]}}]
    out = build_constraint_dicts(songs, n_per_song=2, seed=0)
    assert len(out) == 2
    for c in out:
        assert c["artist"] == "A" and c["title"] == "T"
        assert c["bpm"] == 130 and c["key"] == "F minor"
        assert c["bars"] in (2, 4, 8)
        assert c["track_name"] in ("Drums", "Bass", "Synth", "Pad", "Arp")


def test_load_prompts_returns_empty_on_no_songs():
    from scripts import _neo4j_song_prompts as mod
    with patch.object(mod, "fetch_song_anchors", return_value=[]):
        assert mod.load_prompts() == []
