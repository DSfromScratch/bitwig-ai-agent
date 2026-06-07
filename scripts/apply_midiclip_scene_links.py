"""Wendet die MidiClip→Scene-Migration über den Neo4j-Python-Driver an.

Liest src/knowledge/migrations/link_midiclips_to_scenes.cypher, splittet die
Statements an ';' und führt sie idempotent aus. Gibt IN_SCENE/CLIP_OF-Counts
vor und nach der Migration aus.

Run from repo root:
    .venv/bin/python scripts/apply_midiclip_scene_links.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.knowledge.neo4j_graph import is_available, session  # noqa: E402

MIGRATION = Path(__file__).resolve().parent.parent / "src/knowledge/migrations/link_midiclips_to_scenes.cypher"


def _counts(s) -> dict:
    return {
        "IN_SCENE": s.run("MATCH (:MidiClip)-[r:IN_SCENE]->(:Scene) RETURN count(r) AS c").single()["c"],
        "CLIP_OF": s.run("MATCH (:MidiClip)-[r:CLIP_OF]->(:SoundRecipe) RETURN count(r) AS c").single()["c"],
        "MidiClip": s.run("MATCH (n:MidiClip) RETURN count(n) AS c").single()["c"],
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

    cypher = MIGRATION.read_text(encoding="utf-8")
    stmts = _statements(cypher)

    with session() as s:
        before = _counts(s)
        print(f"Vorher:  {before}")
        for i, stmt in enumerate(stmts, 1):
            s.run(stmt).consume()
            print(f"  ✓ Statement {i}/{len(stmts)} ausgeführt")
        after = _counts(s)
        print(f"Nachher: {after}")
        print(f"Δ IN_SCENE: +{after['IN_SCENE'] - before['IN_SCENE']}, "
              f"Δ CLIP_OF: +{after['CLIP_OF'] - before['CLIP_OF']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
