"""Erzeugt SAMPLED_IN-Kanten zwischen AudioSample und SoundRecipe (Task C.8).

Wendet src/knowledge/migrations/link_audio_samples.cypher über den Neo4j-
Python-Driver an und berichtet die SAMPLED_IN-Counts vor/nach sowie die Zahl
der noch unverknüpften AudioSamples.

Run from repo root:
    .venv/bin/python scripts/link_audio_samples.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.knowledge.neo4j_graph import is_available, session  # noqa: E402

MIGRATION = Path(__file__).resolve().parent.parent / "src/knowledge/migrations/link_audio_samples.cypher"


def _counts(s) -> dict:
    return {
        "SAMPLED_IN": s.run(
            "MATCH (:AudioSample)-[r:SAMPLED_IN]->(:SoundRecipe) RETURN count(r) AS c"
        ).single()["c"],
        "samples_linked": s.run(
            "MATCH (a:AudioSample)-[:SAMPLED_IN]->(:SoundRecipe) RETURN count(DISTINCT a) AS c"
        ).single()["c"],
        "AudioSample_total": s.run(
            "MATCH (n:AudioSample) RETURN count(n) AS c"
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
        print(f"Δ SAMPLED_IN: +{after['SAMPLED_IN'] - before['SAMPLED_IN']}, "
              f"Δ verknüpfte Samples: +{after['samples_linked'] - before['samples_linked']}")

        sample = s.run(
            "MATCH (a:AudioSample)-[r:SAMPLED_IN]->(sr:SoundRecipe) "
            "WHERE r.match IS NOT NULL "
            "RETURN a.filename AS file, sr.track_name AS track, r.match AS via "
            "ORDER BY via, track LIMIT 20"
        ).data()
        print(f"\nRobust verknüpfte Samples ({len(sample)} gezeigt):")
        for r in sample:
            print(f"  [{r['via']}]  {r['file']} → {r['track']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
