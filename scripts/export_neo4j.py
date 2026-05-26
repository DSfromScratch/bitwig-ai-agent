"""Exportiert den Neo4j-Graph als Cypher-Datei (ohne Embeddings).

Erzeugt eine idempotente .cypher-Datei die via cypher-shell eingespielt werden kann.
Embeddings werden nicht exportiert — sie werden via ingest_vectors.py neu berechnet.

Rebuild nach Export (Neo4j läuft als Podman-Container):
    podman exec -i neo4j cypher-shell -u neo4j -p neo4jllm < scripts/neo4j_export.cypher
    .venv/bin/python scripts/ingest_vectors.py

Run from repo root:
    .venv/bin/python scripts/export_neo4j.py [--output scripts/neo4j_export.cypher]
"""
from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Eigenschaften die nie exportiert werden (zu groß oder transient)
SKIP_PROPS = {"embedding"}

# Label-Reihenfolge bestimmt Import-Reihenfolge (Nodes vor Relationships)
NODE_LABELS = [
    "Genre",
    "Device",
    "Parameter",
    "Concept",
    "Workflow",
    "Sound",
    "Pattern",
    "OscCommand",
    "ProductionPattern",
    # Document: wird NICHT exportiert, ingest_vectors.py baut sie neu (~100s)
]

# Unique-Key pro Label (für MERGE)
MERGE_KEY: dict[str, str] = {
    "Genre":             "name",
    "Device":            "name",
    "Parameter":         "name",
    "Concept":           "name",
    "Workflow":          "name",
    "Sound":             "name",
    "Pattern":           "id",
    "OscCommand":        "path",
    "ProductionPattern": "id",
    # Document-Nodes werden NICHT exportiert — ingest_vectors.py baut sie neu
}


def _escape(val) -> str:
    """Wandelt Python-Wert in Cypher-Literal."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return repr(val)
    if isinstance(val, list):
        items = ", ".join(_escape(v) for v in val)
        return f"[{items}]"
    # String: Backslash und einfache Anführungszeichen escapen
    s = str(val).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


def _props_set(props: dict, var: str = "n", skip_key: str | None = None) -> str:
    """Erzeugt SET n.prop = value Kette für alle Props außer merge-key."""
    parts = []
    for k, v in props.items():
        if k in SKIP_PROPS:
            continue
        if k == skip_key:
            continue
        parts.append(f"{var}.{k} = {_escape(v)}")
    if not parts:
        return ""
    return "SET " + ",\n        ".join(parts)


def export_nodes(session, label: str, lines: list[str]) -> int:
    merge_key = MERGE_KEY.get(label)
    if not merge_key:
        print(f"  ⚠ Kein MERGE-Key für Label {label} — übersprungen")
        return 0

    rows = session.run(f"MATCH (n:{label}) RETURN n ORDER BY n.name").data()
    if not rows:
        return 0

    lines.append(f"\n// ── {label} ({len(rows)} Nodes) {'─' * (50 - len(label))}")

    for row in rows:
        props = dict(row["n"])
        # Embeddings und andere Skip-Props entfernen
        props = {k: v for k, v in props.items() if k not in SKIP_PROPS}

        merge_val = props.get(merge_key)
        if merge_val is None:
            continue

        set_clause = _props_set(props, "n", skip_key=merge_key)
        stmt = f"MERGE (n:{label} {{{merge_key}: {_escape(merge_val)}}})"
        if set_clause:
            stmt += f"\n{set_clause}"
        stmt += ";"
        lines.append(stmt)

    return len(rows)


def export_relationships(session, lines: list[str]) -> int:
    rels = session.run("""
        MATCH (a)-[r]->(b)
        WHERE none(l IN labels(a) WHERE l = 'Document')
          AND none(l IN labels(b) WHERE l = 'Document')
        RETURN DISTINCT
            labels(a)[0]  AS src_label,
            labels(b)[0]  AS tgt_label,
            type(r)        AS rel_type,
            a              AS src_node,
            b              AS tgt_node,
            properties(r)  AS rel_props
        ORDER BY type(r), labels(a)[0], labels(b)[0]
    """).data()

    if not rels:
        return 0

    lines.append(f"\n// ── Relationships ({len(rels)}) {'─' * 40}")

    for row in rels:
        src_label = row["src_label"]
        tgt_label = row["tgt_label"]
        rel_type  = row["rel_type"]
        src_props = dict(row["src_node"])
        tgt_props = dict(row["tgt_node"])

        src_key = MERGE_KEY.get(src_label)
        tgt_key = MERGE_KEY.get(tgt_label)

        if not src_key or not tgt_key:
            continue

        src_val = src_props.get(src_key)
        tgt_val = tgt_props.get(tgt_key)

        if src_val is None or tgt_val is None:
            continue

        # Relationship-Properties
        rp = {k: v for k, v in row["rel_props"].items() if k not in SKIP_PROPS}
        if rp:
            rp_str = "{" + ", ".join(f"{k}: {_escape(v)}" for k, v in rp.items()) + "}"
            merge_rel = f"MERGE (a)-[r:{rel_type} {rp_str}]->(b)"
        else:
            merge_rel = f"MERGE (a)-[:{rel_type}]->(b)"

        stmt = (
            f"MATCH (a:{src_label} {{{src_key}: {_escape(src_val)}}}), "
            f"(b:{tgt_label} {{{tgt_key}: {_escape(tgt_val)}}})\n"
            f"{merge_rel};"
        )
        lines.append(stmt)

    return len(rels)


def run(output_path: str) -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session, is_available

    if not is_available():
        print("Neo4j nicht erreichbar — abgebrochen.")
        sys.exit(1)

    lines: list[str] = [
        f"// Neo4j Export — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"// Rebuild: cypher-shell -u neo4j -p neo4jllm < {output_path}",
        f"//          .venv/bin/python scripts/ingest_vectors.py",
        "// Embeddings werden NICHT exportiert (werden neu berechnet).",
        "",
        ":begin",
    ]

    total_nodes = 0
    total_rels  = 0

    with neo4j_session() as s:
        for label in NODE_LABELS:
            n = export_nodes(s, label, lines)
            total_nodes += n
            if n:
                print(f"  {label:25} {n:>5} Nodes")

        total_rels = export_relationships(s, lines)
        print(f"  {'Relationships':25} {total_rels:>5}")

    lines.append("\n:commit")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    size_kb = os.path.getsize(output_path) / 1024
    print(f"\n✓ Exportiert: {output_path}")
    print(f"  {total_nodes} Nodes, {total_rels} Relationships, {size_kb:.0f} KB")
    print(f"\nRestore:\n"
          f"  podman exec -i neo4j cypher-shell -u neo4j -p neo4jllm < {output_path}\n"
          f"  .venv/bin/python scripts/ingest_vectors.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Neo4j → Cypher Export")
    parser.add_argument(
        "--output", "-o",
        default="scripts/neo4j_export.cypher",
        help="Ausgabepfad (Standard: scripts/neo4j_export.cypher)",
    )
    args = parser.parse_args()
    run(args.output)
