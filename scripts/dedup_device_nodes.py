"""Dedupliziert Device-Nodes mit Case-Varianten (Task C.12).

Wendet src/knowledge/migrations/dedup_device_nodes.cypher an. Davor ein
Sicherheits-Check: hängen Relationen an einer lowercase-Variante, wird das
DETACH DELETE übersprungen (sonst Datenverlust) und ein Hinweis ausgegeben.

Run from repo root:
    .venv/bin/python scripts/dedup_device_nodes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.knowledge.neo4j_graph import is_available, session  # noqa: E402

MIGRATION = Path(__file__).resolve().parent.parent / "src/knowledge/migrations/dedup_device_nodes.cypher"

# Statement-Indizes (0-basiert) der DETACH-DELETE-Phase im Migrations-File.
_DELETE_STMT_PREFIX = "MATCH (lower:Device)"


def _counts(s) -> dict:
    row = s.run(
        "MATCH (d:Device) RETURN count(d) AS total, "
        "count(DISTINCT toLower(trim(d.name))) AS distinct_names"
    ).single()
    return {"Device_total": row["total"], "Device_distinct": row["distinct_names"]}


def _rels_on_lowercase_dups(s) -> int:
    return s.run("""
        MATCH (lower:Device) WHERE lower.name = toLower(lower.name)
        MATCH (titled:Device)
        WHERE titled.name <> lower.name
          AND toLower(trim(titled.name)) = toLower(trim(lower.name))
        MATCH (lower)-[r]-()
        RETURN count(r) AS c
    """).single()["c"]


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
        dup_groups = before["Device_total"] - before["Device_distinct"]
        print(f"Vorher:  {before}  → {dup_groups} Duplikat-Nodes")

        stray = _rels_on_lowercase_dups(s)
        if stray > 0:
            print(f"⚠️  {stray} Relationen hängen an lowercase-Duplikaten — "
                  "DETACH DELETE würde sie verlieren. Abbruch vor dem Löschen.")
            print("    → Generisches Rewiring nötig (APOC apoc.refactor.mergeNodes).")
            # Nur den UUID-Backfill (Statement 1) ausführen, NICHT löschen.
            s.run(stmts[0]).consume()
            print("    ✓ builtin_uuid-Backfill ausgeführt (ohne Löschen).")
            return 2

        for i, stmt in enumerate(stmts, 1):
            s.run(stmt).consume()
            print(f"  ✓ Statement {i}/{len(stmts)} ausgeführt")

        after = _counts(s)
        print(f"Nachher: {after}")
        removed = before["Device_total"] - after["Device_total"]
        print(f"Δ Device-Nodes: -{removed} (jetzt total == distinct: "
              f"{after['Device_total'] == after['Device_distinct']})")

        # Verifikation: USES_DEVICE-Kanten weiterhin intakt?
        ud = s.run(
            "MATCH (:SoundRecipe)-[r:USES_DEVICE]->(:Device) RETURN count(r) AS c"
        ).single()["c"]
        print(f"USES_DEVICE-Kanten (unverändert erwartet): {ud}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
