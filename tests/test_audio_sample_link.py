"""Tests für SAMPLED_IN: AudioSample → SoundRecipe (Task C.8).

Statisch (kein Neo4j nötig): prüft die robuste, projekt-agnostische Verknüpfung
(Stem == track_name bzw. eindeutiges primary_device) in Migration und Ingest
sowie den Consumer im knowledge_tool.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "src/knowledge/migrations/link_audio_samples.cypher"
RUNNER = ROOT / "scripts/link_audio_samples.py"
INGEST = ROOT / "scripts/ingest_audio_samples.py"
KNOWLEDGE = ROOT / "src/agent/tools/knowledge/vector_search.py"


def test_migration_rule_a_matches_track_name():
    cy = MIGRATION.read_text(encoding="utf-8")
    assert "MERGE (a)-[r:SAMPLED_IN]->(sr)" in cy
    assert "toLower(trim(sr.track_name)) = stem" in cy
    # Bounce-Suffix wird abgeschnitten.
    assert "split(s0, '-bounce')[0]" in cy


def test_migration_rule_b_requires_unique_primary_device():
    cy = MIGRATION.read_text(encoding="utf-8")
    assert "toLower(trim(sr.primary_device)) = stem" in cy
    # Eindeutigkeit erzwungen (kein Fan-out bei Geräten in mehreren Tracks).
    assert "size(recipes) = 1" in cy


def test_ingest_has_project_agnostic_linker():
    src = INGEST.read_text(encoding="utf-8")
    assert "_link_samples_robust" in src
    assert "size(recipes) = 1" in src


def test_knowledge_tool_surfaces_samples():
    src = KNOWLEDGE.read_text(encoding="utf-8")
    assert "SAMPLED_IN" in src
    assert "Samples:" in src


def test_runner_imports_neo4j_session():
    src = RUNNER.read_text(encoding="utf-8")
    assert "from src.knowledge.neo4j_graph import is_available, session" in src
