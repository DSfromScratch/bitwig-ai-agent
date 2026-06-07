"""Unit-Tests für die in C.6 extrahierten _query_neo4j-Sektions-Helper.

Verifiziert die reine Refaktorierung von `_query_neo4j` (372 Zeilen) in
fokussierte, einzeln testbare Sektions-Funktionen — ohne laufendes Neo4j.
"""
from unittest.mock import MagicMock

import pytest

from src.agent.tools.knowledge import knowledge_tool as kt

pytestmark = pytest.mark.unit


def _result(rows):
    """Baut ein Fake-Neo4j-Result, das .data() (und .single()) unterstützt."""
    res = MagicMock()
    res.data.return_value = rows
    res.single.return_value = rows[0] if rows else None
    return res


def test_extract_keywords_filters_stopwords_and_short_words():
    assert kt._extract_keywords("Was ist ein Polysynth für Techno?") == [
        "ist", "ein", "polysynth", "techno",
    ]
    # nur Stopwörter / zu kurze Wörter → leer
    assert kt._extract_keywords("was wie der die") == []


def test_section_concepts_formats_and_traverses_devices():
    s = MagicMock()
    s.run.side_effect = [
        _result([{"name": "Sidechain", "desc": "Ducking", "use_case": "Pumpen",
                  "category": "mixing"}]),
        _result([{"n": "Compressor+"}]),
    ]
    parts = kt._section_concepts(s, ["sidechain"])
    assert len(parts) == 1
    assert "**Bitwig-Konzepte:**" in parts[0]
    assert "**Sidechain**" in parts[0]
    assert "Wann: Pumpen" in parts[0]
    assert "Devices: Compressor+" in parts[0]


def test_section_concepts_empty_returns_empty_list():
    s = MagicMock()
    s.run.return_value = _result([])
    assert kt._section_concepts(s, ["nichts"]) == []


def test_section_devices_includes_usage_traversals():
    s = MagicMock()
    s.run.side_effect = [
        _result([{"name": "Poly Grid", "type": "instrument", "category": "synth",
                  "desc": "Modular", "use_case": "Sounddesign", "tips": None}]),
        _result([]),                              # params
        _result([]),                              # similar
        _result([]),                              # wf_using
        _result([]),                              # genre_uses
        _result([{"project": "MyProj", "track": "Lead", "primary": True}]),  # recipe_uses
        _result([{"tab": "Instruments", "path": "Grid", "panel": None,
                  "uuid": None, "load_cmd": None}]),  # nav
    ]
    parts = kt._section_devices(s, ["poly"])
    assert len(parts) == 1
    assert "**Poly Grid**" in parts[0]
    assert "Benutzt in: MyProj/Lead ★" in parts[0]


def test_section_workflows_recording_priority(monkeypatch):
    s = MagicMock()
    s.run.side_effect = [
        _result([{"name": "Audio aufnehmen", "desc": "Arm + Rec",
                  "steps": "Track wählen\nArm\nPlay"}]),  # 4a recording
        _result([]),                                       # 4 general workflows
    ]
    parts = kt._section_workflows(s, ["aufnehmen"], "wie kann ich aufnehmen")
    assert any("Audio aufnehmen" in p for p in parts)


def test_section_artists_handles_missing_json_without_unbound_error():
    """Regression: json wurde früher nur inline in Sektion 2/4 importiert —
    bei reinem Artist-Treffer drohte UnboundLocalError. Jetzt top-level."""
    s = MagicMock()
    s.run.return_value = _result([
        {"name": "Daft Punk", "genre": "House", "bpm": "120", "key": "F minor",
         "style": "Filtered synths", "devices_json": '["Polysynth", "Filter"]',
         "note_plan": None, "score": 1.0},
    ])
    parts = kt._section_artists(s, ["daft"])
    assert len(parts) == 1
    assert "**Künstler: Daft Punk**" in parts[0]
    assert "Devices: Polysynth, Filter" in parts[0]


def test_query_neo4j_empty_keywords_short_circuits():
    # Nur Stopwörter → kein Neo4j-Zugriff, leerer String.
    assert kt._query_neo4j("was wie der") == ""
