"""Tests für die Device-Deduplizierung (Task C.12).

Statisch (kein Neo4j nötig): prüft, dass die Migration vor dem Löschen die
builtin_uuid in die kanonische Node übernimmt und der Runner einen Sicherheits-
Check gegen Relationen an lowercase-Duplikaten hat.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "src/knowledge/migrations/dedup_device_nodes.cypher"
RUNNER = ROOT / "scripts/dedup_device_nodes.py"


def test_migration_backfills_uuid_before_delete():
    cy = MIGRATION.read_text(encoding="utf-8")
    set_pos = cy.find("coalesce(titled.builtin_uuid, lower.builtin_uuid)")
    del_pos = cy.find("DETACH DELETE lower")
    assert set_pos != -1, "UUID-Backfill fehlt"
    assert del_pos != -1, "DELETE fehlt"
    # Backfill MUSS vor dem Löschen stehen (sonst Datenverlust).
    assert set_pos < del_pos


def test_migration_matches_only_case_duplicates():
    cy = MIGRATION.read_text(encoding="utf-8")
    # Kanonisch = Title-Case; gelöscht wird die lowercase-Variante.
    assert "lower.name = toLower(lower.name)" in cy
    assert "toLower(trim(titled.name)) = toLower(trim(lower.name))" in cy
    assert "titled.name <> lower.name" in cy


def test_runner_has_relationship_safety_check():
    src = RUNNER.read_text(encoding="utf-8")
    assert "_rels_on_lowercase_dups" in src
    # Bei vorhandenen Relationen darf NICHT gelöscht werden.
    assert "Abbruch vor dem Löschen" in src
