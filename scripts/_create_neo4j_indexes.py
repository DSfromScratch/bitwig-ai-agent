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
        "sound_recipe_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX sound_recipe_embedding IF NOT EXISTS "
        "FOR (n:SoundRecipe) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "audio_sample_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX audio_sample_embedding IF NOT EXISTS "
        "FOR (n:AudioSample) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "gridmodule_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX gridmodule_embedding IF NOT EXISTS "
        "FOR (n:GridModule) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "gridanalysis_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX gridanalysis_embedding IF NOT EXISTS "
        "FOR (n:GridAnalysis) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "gridworkflow_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX gridworkflow_embedding IF NOT EXISTS "
        "FOR (n:GridWorkflow) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "midiclip_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX midiclip_embedding IF NOT EXISTS "
        "FOR (n:MidiClip) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "genre_pattern_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX genre_pattern_embedding IF NOT EXISTS "
        "FOR (n:GenrePattern) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "artist_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX artist_embedding IF NOT EXISTS "
        "FOR (n:Artist) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "song_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX song_embedding IF NOT EXISTS "
        "FOR (n:Song) ON n.embedding "
        "OPTIONS {indexConfig: {`vector.dimensions`: 768, `vector.similarity_function`: 'cosine'}}"
    ),
    (
        "project_template_embedding (Vektor 768d)",
        "CREATE VECTOR INDEX project_template_embedding IF NOT EXISTS "
        "FOR (n:ProjectTemplate) ON n.embedding "
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
