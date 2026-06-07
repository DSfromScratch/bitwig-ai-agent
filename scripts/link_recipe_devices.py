"""Erzeugt USES_DEVICE-Kanten zwischen SoundRecipe und Device (Task C.11).

Wendet src/knowledge/migrations/link_recipe_devices.cypher über den Neo4j-
Python-Driver an und berichtet die USES_DEVICE-Counts vor/nach. Gibt zusätzlich
die Top-Devices nach Verwendungshäufigkeit aus ("wo wird X benutzt?").

Run from repo root:
    .venv/bin/python scripts/link_recipe_devices.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.knowledge.neo4j_graph import is_available, session  # noqa: E402

MIGRATION = Path(__file__).resolve().parent.parent / "src/knowledge/migrations/link_recipe_devices.cypher"


def _counts(s) -> dict:
    return {
        "USES_DEVICE": s.run(
            "MATCH (:SoundRecipe)-[r:USES_DEVICE]->(:Device) RETURN count(r) AS c"
        ).single()["c"],
        "recipes_linked": s.run(
            "MATCH (sr:SoundRecipe)-[:USES_DEVICE]->(:Device) RETURN count(DISTINCT sr) AS c"
        ).single()["c"],
        "SoundRecipe_total": s.run(
            "MATCH (n:SoundRecipe) RETURN count(n) AS c"
        ).single()["c"],
    }


def _statements(text: str) -> list[str]:
    stmts, buf = [], []
    for line in text.splitlines():
        if line.strip().startswith("//") or not line.strip():
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmts.append("\n".join(buf).rstrip().rstrip(";"))
            buf = []
    if buf:
        stmts.append("\n".join(buf))
    return [s for s in stmts if s.strip()]


def main() -> int:
    if not is_available():
        print("✗ Neo4j nicht verfügbar — Migration übersprungen.")
        return 1

    stmts = _statements(MIGRATION.read_text(encoding="utf-8"))

    with session() as s:
        before = _counts(s)
        print(f"Vorher:  {before}")
        for i, stmt in enumerate(stmts, 1):
            s.run(stmt).consume()
            print(f"  ✓ Statement {i}/{len(stmts)} ausgeführt")
        after = _counts(s)
        print(f"Nachher: {after}")
        print(f"Δ USES_DEVICE: +{after['USES_DEVICE'] - before['USES_DEVICE']}")

        top = s.run(
            "MATCH (sr:SoundRecipe)-[:USES_DEVICE]->(d:Device) "
            "RETURN d.name AS device, count(DISTINCT sr) AS tracks "
            "ORDER BY tracks DESC LIMIT 15"
        ).data()
        print("\nTop-Devices nach Verwendung (in wie vielen Tracks):")
        for r in top:
            print(f"  {r['tracks']:3d}x  {r['device']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
