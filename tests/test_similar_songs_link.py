"""Tests für SIMILAR_TO zwischen Song-Embeddings (Task C.10).

Statisch (kein Neo4j nötig): prüft, dass die Migration top-k-Nearest-Neighbor
über den song_embedding-Vektorindex verwendet, Self-Loops ausschließt und die
Kante mit score/reason annotiert.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "src/knowledge/migrations/link_similar_songs.cypher"
RUNNER = ROOT / "scripts/link_similar_songs.py"


def test_migration_uses_song_vector_index():
    cy = MIGRATION.read_text(encoding="utf-8")
    assert "db.index.vector.queryNodes('song_embedding'" in cy
    # top-k (k=4 → 3 Nachbarn nach Self-Ausschluss), nicht globaler Threshold.
    assert "queryNodes('song_embedding', 4" in cy


def test_migration_excludes_self_and_annotates_edge():
    cy = MIGRATION.read_text(encoding="utf-8")
    assert "elementId(b) <> elementId(a)" in cy
    assert "MERGE (a)-[r:SIMILAR_TO]->(b)" in cy
    assert "r.score" in cy
    assert "r.reason = 'embedding'" in cy


def test_runner_exists_and_imports_neo4j_session():
    src = RUNNER.read_text(encoding="utf-8")
    assert "from src.knowledge.neo4j_graph import is_available, session" in src
