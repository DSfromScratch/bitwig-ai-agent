#!/usr/bin/env python3
"""Einmalig: Vektor- und Volltextindizes in Neo4j anlegen."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge.neo4j_graph import session

INDEXES = [
    (
        "document_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX document_embedding IF NOT EXISTS "
        "FOR (d:Document) ON d.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "knowledgeqa_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX knowledgeqa_embedding IF NOT EXISTS "
        "FOR (k:KnowledgeQA) ON k.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "device_search (Volltext)",
        "CREATE FULLTEXT INDEX device_search IF NOT EXISTS "
        "FOR (d:Device) ON EACH [d.name, d.description, d.category]"
    ),
    (
        "workflow_search (Volltext)",
        "CREATE FULLTEXT INDEX workflow_search IF NOT EXISTS "
        "FOR (w:Workflow) ON EACH [w.name, w.description, w.steps]"
    ),
]

print("=== Indizes anlegen ===")
with session() as s:
    for name, cypher in INDEXES:
        try:
            s.run(cypher)
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ⚠ {name}: {e}")

print("\n=== Datenbankinhalt ===")
with session() as s:
    for row in s.run("MATCH (n) RETURN labels(n)[0] AS l, count(n) AS c ORDER BY c DESC").data():
        print(f"  {row['l']:<22} {row['c']:>4} Nodes")
    print()
    for r in s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS c ORDER BY c DESC").data():
        print(f"  :{r['t']:<25} {r['c']:>4} Kanten")
