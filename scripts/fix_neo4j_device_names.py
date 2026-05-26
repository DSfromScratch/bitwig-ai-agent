"""Fix wrong Device node names in Neo4j.

Run once from repo root:
    python scripts/fix_neo4j_device_names.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.knowledge.neo4j_graph import session as neo4j_session, is_available

RENAMES = [
    ("E-Kick",  "v9 Kick"),
    ("E-Snare", "v9 Snare"),
    ("E-HiHat", "v9 Hat Closed"),
    ("E-Hat",   "v9 Hat Closed"),
    ("E-Clap",  "v9 Clap"),
    ("E-Tom",   "v9 Tom"),
]

def run() -> None:
    if not is_available():
        print("Neo4j nicht erreichbar — abgebrochen.")
        sys.exit(1)

    with neo4j_session() as s:
        for old, new in RENAMES:
            result = s.run(
                "MATCH (d:Device {name: $old}) SET d.name = $new RETURN count(d) AS n",
                old=old, new=new,
            ).single()
            n = result["n"] if result else 0
            print(f"  {old!r} → {new!r}: {n} Node(s) aktualisiert")

    print("Fertig.")


if __name__ == "__main__":
    run()
