"""Tests für die MidiClip→Scene-Relation (Task C.7).

Statisch (kein Neo4j nötig): prüft, dass der Ingest-Code track_index/scene_idx
persistiert und dass die Backfill-Migration über scene_idx (robust) statt
primär über scene_name (mehrdeutig) verknüpft.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
INGEST = ROOT / "scripts/ingest_midi_clips.py"
MIGRATION = ROOT / "src/knowledge/migrations/link_midiclips_to_scenes.cypher"


def test_ingest_persists_scene_and_track_index():
    src = INGEST.read_text(encoding="utf-8")
    # Die MidiClip-Relations-MATCHes filtern auf diese Properties — sie müssen
    # daher im SET-Block geschrieben werden, sonst laufen die MERGEs ins Leere.
    assert "n.track_index     = $ti" in src
    assert "n.scene_idx       = $scene_idx" in src


def test_migration_uses_scene_idx_as_primary_key():
    cy = MIGRATION.read_text(encoding="utf-8")
    assert "MERGE (mc)-[:IN_SCENE]->(sc)" in cy
    # Primäres Matching über scene_idx (1-basiert), nicht über mehrdeutigen Namen.
    assert "Scene {idx: mc.scene_idx, project: mc.project}" in cy
    # Name-Fallback nur für eindeutige Treffer (size == 1), um Fan-out zu vermeiden.
    assert "size(scenes) = 1" in cy


def test_migration_backfills_clip_of():
    cy = MIGRATION.read_text(encoding="utf-8")
    assert "MERGE (mc)-[:CLIP_OF]->(sr)" in cy
