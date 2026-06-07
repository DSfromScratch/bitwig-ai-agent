// SAMPLED_IN-Kanten: AudioSample -> SoundRecipe (welches Sample/welcher Bounce gehoert zu welchem Track).
// Apply (Neo4j laeuft als Podman-Container):
//     podman exec -i neo4j cypher-shell -u neo4j -p neo4jllm < src/knowledge/migrations/link_audio_samples.cypher
// Alternativ via Python-Driver (mit Vorher/Nachher-Report):
//     .venv/bin/python scripts/link_audio_samples.py
//
// AudioSample-Nodes tragen nur filename/category/project (kein track_index).
// Frueher wurde die Track-Zuordnung in scripts/ingest_audio_samples.py ueber ein
// HARDCODED, projekt-spezifisches Mapping ("polysynth" -> "Sharp Arp" usw.) erzeugt
// — nicht reproduzierbar fuer neue Projekte. Diese Migration etabliert SAMPLED_IN
// projekt-agnostisch ueber zwei ROBUSTE, eindeutige Signale (additiv, idempotent):
//
//   Regel A: Bounce-/Sample-Stem == track_name (exakt, case-insensitive). Bitwig
//            rendert Bounces als "<TrackName>-bounce-N.wav" — der Stem ist damit
//            der zuverlaessigste Schluessel.
//   Regel B: Bounce-Stem == primary_device UND genau EIN Track im Projekt nutzt
//            dieses Geraet als Primaer-Instrument (z.B. "Drum Machine-bounce" ->
//            der einzige Drum-Machine-Track). Mehrdeutige Geraete (z.B. "Poly Grid"
//            in 13 Tracks) werden bewusst NICHT verknuepft, um Fan-out zu vermeiden.

// -- Regel A: Stem == track_name (exakt) -------------------------------------
MATCH (a:AudioSample)
WHERE a.filename IS NOT NULL
WITH a, replace(replace(toLower(a.filename), '.wav', ''), '.aiff', '') AS s0
WITH a, CASE WHEN s0 CONTAINS '-bounce' THEN trim(split(s0, '-bounce')[0]) ELSE s0 END AS stem
MATCH (sr:SoundRecipe {project: a.project})
WHERE toLower(trim(sr.track_name)) = stem
MERGE (a)-[r:SAMPLED_IN]->(sr)
SET r.match = 'track_name';

// -- Regel B: Stem == eindeutiges primary_device -----------------------------
MATCH (a:AudioSample)
WHERE a.filename IS NOT NULL AND toLower(a.filename) CONTAINS '-bounce'
WITH a, replace(replace(toLower(a.filename), '.wav', ''), '.aiff', '') AS s0
WITH a, trim(split(s0, '-bounce')[0]) AS stem
MATCH (sr:SoundRecipe {project: a.project})
WHERE toLower(trim(sr.primary_device)) = stem
WITH a, stem, collect(DISTINCT sr) AS recipes
WHERE size(recipes) = 1
WITH a, recipes[0] AS sr
MERGE (a)-[r:SAMPLED_IN]->(sr)
SET r.match = coalesce(r.match, 'primary_device');
