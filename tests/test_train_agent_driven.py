"""Tests für scripts/train_agent_driven.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_format_prompt_with_song_mentions_artist_and_genre():
    from scripts.train_agent_driven import _format_prompt
    p = _format_prompt("Daft Punk - Da Funk", "house", bars=4, key="C minor")
    assert "Daft Punk - Da Funk" in p
    assert "house" in p
    assert "4" in p
    assert "write_pattern_raw" in p  # Hinweis aufs Hybrid-Tool


def test_format_prompt_without_song_falls_back_to_genre():
    from scripts.train_agent_driven import _format_prompt
    p = _format_prompt(None, "techno", bars=2, key="A minor", style="hard")
    assert "techno" in p
    assert "hard" in p


def test_append_pair_writes_jsonl(tmp_path: Path):
    from scripts.train_agent_driven import _append_pair
    out = tmp_path / "log.jsonl"
    _append_pair(out, "prompt1", "answer1", 0.75, {"foo": "bar"})
    _append_pair(out, "prompt2", "answer2", 0.42, {"baz": 1})
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["prompt"] == "prompt1"
    assert rows[1]["score"] == 0.42
    assert rows[0]["meta"]["foo"] == "bar"
    assert "timestamp" in rows[0]


def test_run_batch_iterates_all_recipes_and_logs(tmp_path: Path):
    """Mock _ask_agent → batch läuft alle recipes durch und schreibt jsonl."""
    from scripts import train_agent_driven as mod
    out = tmp_path / "session.jsonl"
    recipes = [
        {"song": "Daft Punk - Da Funk", "genre": "house", "bars": 4, "key": "C minor"},
        {"song": None,                  "genre": "techno", "bars": 2, "key": "A minor"},
    ]
    with patch.object(mod, "_ask_agent", return_value=('{"tool":"write_pattern","args":{}}', {})):
        with patch.object(mod, "_score_answer", return_value=(0.6, {})):
            n = mod.run_batch(out, recipes)
    assert n == 2
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["meta"]["song"] == "Daft Punk - Da Funk"


def test_run_neo4j_anchors_skips_when_no_songs(tmp_path: Path):
    from scripts import train_agent_driven as mod
    with patch("scripts._neo4j_song_prompts.fetch_song_anchors", return_value=[]):
        n = mod.run_neo4j_anchors(tmp_path / "log.jsonl", max_anchors=5)
    assert n == 0


def test_run_neo4j_anchors_builds_recipes_from_song_metadata(tmp_path: Path):
    from scripts import train_agent_driven as mod
    songs = [
        {"title": "Da Funk", "artist": "Daft Punk", "key": "C",
         "metadata": {"musicbrainz_tags": ["house"]}},
        {"title": "Levels",  "artist": "Avicii",    "key": "A minor",
         "metadata": {}},
    ]
    with patch.object(mod, "fetch_song_anchors", return_value=songs, create=True):
        # fetch wird lokal in run_neo4j_anchors importiert — patche via module-name:
        with patch("scripts._neo4j_song_prompts.fetch_song_anchors", return_value=songs):
            with patch.object(mod, "_ask_agent", return_value=("ok", {})):
                with patch.object(mod, "_score_answer", return_value=(0.7, {})):
                    n = mod.run_neo4j_anchors(tmp_path / "log.jsonl")
    assert n == 2
    rows = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert any("Daft Punk - Da Funk" in r["prompt"] for r in rows)
    # Genre wird aus musicbrainz_tags abgeleitet:
    assert any(r["meta"].get("genre") == "house" for r in rows)
