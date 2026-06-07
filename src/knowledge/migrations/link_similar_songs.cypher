// SIMILAR_TO-Kanten zwischen Song-Embeddings (projekt-/songweite Vektor-Ähnlichkeit).
// Apply (Neo4j läuft als Podman-Container):
//     podman exec -i neo4j cypher-shell -u neo4j -p neo4jllm < src/knowledge/migrations/link_similar_songs.cypher
// Alternativ via Python-Driver (mit Vorher/Nachher-Report):
//     .venv/bin/python scripts/link_similar_songs.py
//
// Song-Nodes tragen das projektweite Content-Embedding (chord_progression, key,
// bpm, note_plan …). Da alle Songs denselben musikalischen Embedding-Raum teilen,
// liegen die Cosine-Scores eng beieinander (~0.90–0.95) — ein flacher Schwellwert
// würde den Graphen vollständig vernetzen. Deshalb top-k-Nearest-Neighbor (k=3)
// pro Song statt globalem Threshold; der 0.85-Floor verhindert schwache Kanten,
// falls der Korpus wächst.

MATCH (a:Song)
WHERE a.embedding IS NOT NULL
CALL db.index.vector.queryNodes('song_embedding', 4, a.embedding)
YIELD node AS b, score
WHERE elementId(b) <> elementId(a) AND score >= 0.85
MERGE (a)-[r:SIMILAR_TO]->(b)
SET r.score = round(score, 4), r.reason = 'embedding';
