"""Erzeugt SIMILAR_TO-Kanten zwischen Song-Embeddings (Task C.10).

Wendet src/knowledge/migrations/link_similar_songs.cypher über den Neo4j-
Python-Driver an und berichtet die SIMILAR_TO-Counts (nach Reason) vor/nach.

Run from repo root:
    .venv/bin/python scripts/link_similar_songs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.knowledge.neo4j_graph import is_available, session  # noqa: E402

MIGRATION = Path(__file__).resolve().parent.parent / "src/knowledge/migrations/link_similar_songs.cypher"


def _counts(s) -> dict:
    return {
        "SIMILAR_TO_song": s.run(
            "MATCH (:Song)-[r:SIMILAR_TO]->(:Song) RETURN count(r) AS c"
        ).single()["c"],
        "SIMILAR_TO_total": s.run(
            "MATCH ()-[r:SIMILAR_TO]->() RETURN count(r) AS c"
        ).single()["c"],
        "Song_with_embedding": s.run(
            "MATCH (n:Song) WHERE n.embedding IS NOT NULL RETURN count(n) AS c"
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
        print(f"Δ SIMILAR_TO (Song↔Song): +{after['SIMILAR_TO_song'] - before['SIMILAR_TO_song']}")

        edges = s.run(
            "MATCH (a:Song)-[r:SIMILAR_TO]->(b:Song) "
            "RETURN a.name AS a, b.name AS b, r.score AS score "
            "ORDER BY a, score DESC"
        ).data()
        print(f"\n{len(edges)} Song→Song-Kanten:")
        for e in edges:
            print(f"  {e['score']:.3f}  {e['a']} → {e['b']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
