// Macht MidiClip→Scene zu einer echten Graph-Relation (statt nur scene_name-String).
// Apply (Neo4j läuft als Podman-Container):
//     podman exec -i neo4j cypher-shell -u neo4j -p neo4jllm < src/knowledge/migrations/link_midiclips_to_scenes.cypher
// Alternativ via Python-Driver:
//     .venv/bin/python scripts/apply_midiclip_scene_links.py
//
// Hintergrund: store_midi_clip() persistierte früher track_index/scene_idx nicht
// auf dem MidiClip-Node, weshalb die IN_SCENE-/CLIP_OF-MATCHes (die auf diese
// Properties filtern) ins Leere liefen. Diese Migration backfillt die Relationen
// für bereits vorhandene Nodes idempotent.

// ── 1. IN_SCENE über scene_idx (robust, 1-basiert wie Bitwig) ────────────────
MATCH (mc:MidiClip)
WHERE mc.scene_idx IS NOT NULL AND mc.scene_idx > 0
MATCH (sc:Scene {idx: mc.scene_idx, project: mc.project})
MERGE (mc)-[:IN_SCENE]->(sc);

// ── 2. CLIP_OF über track_index ──────────────────────────────────────────────
MATCH (mc:MidiClip)
WHERE mc.track_index IS NOT NULL
MATCH (sr:SoundRecipe {track_index: mc.track_index, project: mc.project})
MERGE (mc)-[:CLIP_OF]->(sr);

// ── 3. IN_SCENE-Fallback für Alt-Nodes ohne scene_idx ────────────────────────
//      Nur wenn der scene_name EINDEUTIG genau eine Scene trifft (sonst Fan-out
//      durch gleichnamige Szenen-Duplikate vermeiden).
MATCH (mc:MidiClip)
WHERE mc.scene_idx IS NULL AND mc.scene_name IS NOT NULL AND mc.scene_name <> ""
CALL (mc) {
    MATCH (sc:Scene {project: mc.project})
    WHERE toLower(sc.name) = toLower(mc.scene_name)
    RETURN collect(sc) AS scenes
}
WITH mc, scenes
WHERE size(scenes) = 1
WITH mc, scenes[0] AS sc
SET mc.scene_idx = sc.idx
MERGE (mc)-[:IN_SCENE]->(sc);
