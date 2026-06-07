"""Tests für USES_DEVICE: SoundRecipe → Device (Task C.11).

Statisch (kein Neo4j nötig): prüft Migration, Ingest-Persistierung der Relation
und den Consumer im knowledge_tool.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "src/knowledge/migrations/link_recipe_devices.cypher"
RUNNER = ROOT / "scripts/link_recipe_devices.py"
INGEST_LIVE = ROOT / "scripts/ingest_live_project.py"
INGEST_ARR = ROOT / "scripts/ingest_arranger_tracks.py"
KNOWLEDGE = ROOT / "src/agent/tools/knowledge/knowledge_tool.py"


def test_migration_creates_uses_device_with_canonical_node():
    cy = MIGRATION.read_text(encoding="utf-8")
    assert "MERGE (sr)-[r:USES_DEVICE]->(canonical)" in cy
    # Kanonische Auswahl je Name über Grad (vermeidet Case-Duplikat-Inflation).
    assert "COUNT { (d)--() } AS degree" in cy
    assert "head(collect(d)) AS canonical" in cy
    # Primär-Instrument wird markiert.
    assert "r.is_primary" in cy
    # Re-Run-sicher: alte Kanten werden zuerst gelöscht.
    assert "DELETE r" in cy


def test_ingest_creates_uses_device_relation():
    for f in (INGEST_LIVE, INGEST_ARR):
        src = f.read_text(encoding="utf-8")
        assert "MERGE (sr)-[r:USES_DEVICE]->(canonical)" in src, f.name


def test_arranger_persists_devices_array():
    src = INGEST_ARR.read_text(encoding="utf-8")
    assert "n.devices        = $devices" in src


def test_knowledge_tool_consumes_uses_device():
    src = KNOWLEDGE.read_text(encoding="utf-8")
    assert "USES_DEVICE" in src
    assert "Benutzt in:" in src


def test_runner_imports_neo4j_session():
    src = RUNNER.read_text(encoding="utf-8")
    assert "from src.knowledge.neo4j_graph import is_available, session" in src
