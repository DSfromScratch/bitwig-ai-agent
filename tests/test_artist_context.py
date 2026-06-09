"""Tests für get_artist_context (Task C.9).

Mock-basiert (kein Neo4j nötig): prüft Registrierung, Formatierung des
Artist-Profils und das Fehler-Handling bei unbekanntem Künstler.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_tool_is_registered():
    from src.agent.tools import ALL_TOOLS
    # get_artist_context ist in query_knowledge integriert (Phase 3)
    assert "query_knowledge" in [t.name for t in ALL_TOOLS]


def test_empty_name_returns_hint():
    from src.agent.tools.knowledge.artist_tool import get_artist_context
    with patch("src.knowledge.neo4j_graph.is_available", return_value=True), \
         patch("src.knowledge.neo4j_graph.session"):
        out = get_artist_context.invoke({"artist_name": "  "})
    assert "Künstlernamen" in out


def _fake_session(artist_row, songs=None, genres=None, similar=None):
    """Baut eine Session, deren run() je nach Query unterschiedliche Daten liefert."""
    sess = MagicMock()

    def run(query, **kwargs):
        res = MagicMock()
        if "MATCH (a:Artist)" in query and "RETURN a.name AS name, a.genre" in query:
            res.single.return_value = artist_row
        elif ":BY]->(a:Artist" in query and "song.name" in query:
            res.data.return_value = songs or []
        elif "ASSOCIATED_WITH" in query:
            res.data.return_value = genres or []
        elif "SIMILAR_TO" in query:
            res.data.return_value = similar or []
        else:
            res.single.return_value = None
            res.data.return_value = []
        return res

    sess.run.side_effect = run
    ctx = MagicMock()
    ctx.__enter__.return_value = sess
    ctx.__exit__.return_value = False
    return ctx


def test_formats_full_artist_profile():
    from src.agent.tools.knowledge.artist_tool import get_artist_context
    artist = {
        "name": "Daft Punk", "genre": "French House", "style": "Filtered synths",
        "bpm": "120–128", "key": "F minor",
        "devices_json": '["Phase-4", "FM-4"]', "note_plan": None, "score": 0.9,
    }
    songs = [{"name": "Da Funk", "bpm": "121", "key": "C minor", "chords": None}]
    genres = [{"name": "French House"}]
    similar = [{"song": "Windowlicker", "artist": "Aphex Twin", "score": 0.94}]
    ctx = _fake_session(artist, songs, genres, similar)
    with patch("src.knowledge.neo4j_graph.is_available", return_value=True), \
         patch("src.knowledge.neo4j_graph.session", return_value=ctx):
        out = get_artist_context.invoke({"artist_name": "Daft Punk"})
    assert "Daft Punk" in out
    assert "Phase-4" in out                 # Devices
    assert "Da Funk" in out                 # Referenz-Song via :BY
    assert "Windowlicker" in out            # ähnlich via :SIMILAR_TO
    assert "French House" in out            # assoziiertes Genre


def test_unknown_artist_lists_available():
    from src.agent.tools.knowledge.artist_tool import get_artist_context

    sess = MagicMock()

    def run(query, **kwargs):
        res = MagicMock()
        if "RETURN a.name AS name, a.genre" in query:
            res.single.return_value = None
        else:
            res.data.return_value = [{"n": "Aphex Twin"}, {"n": "Daft Punk"}]
        return res

    sess.run.side_effect = run
    ctx = MagicMock()
    ctx.__enter__.return_value = sess
    ctx.__exit__.return_value = False

    with patch("src.knowledge.neo4j_graph.is_available", return_value=True), \
         patch("src.knowledge.neo4j_graph.session", return_value=ctx):
        out = get_artist_context.invoke({"artist_name": "Unknown"})
    assert "Kein Künstler" in out
    assert "Daft Punk" in out               # Vorschlagsliste
