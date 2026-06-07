// USES_DEVICE-Kanten: SoundRecipe → Device (welcher Track benutzt welches Instrument/welchen Effekt).
// Apply (Neo4j läuft als Podman-Container):
//     podman exec -i neo4j cypher-shell -u neo4j -p neo4jllm < src/knowledge/migrations/link_recipe_devices.cypher
// Alternativ via Python-Driver (mit Vorher/Nachher-Report):
//     .venv/bin/python scripts/link_recipe_devices.py
//
// Bisher wurden die Devices eines Tracks nur als String-Array-Property
// (sr.devices / sr.primary_device) gespeichert — "wo wird Device X benutzt?"
// war nur per Property-Scan beantwortbar, nicht per Graph-Traversal. Diese
// Migration etabliert die echte Relation und markiert das Primaer-Instrument.
//
// Daten-Eigenheit: Device-Nodes existieren teils doppelt, die sich nur in der
// Gross-/Kleinschreibung unterscheiden (z.B. "Poly Grid" vs "poly grid"). In
// 127/127 Faellen traegt die kanonische (hoeher-gradige) Variante die kuratierten
// Parameter. Deshalb wird per Name GENAU EINE kanonische Device-Node gewaehlt
// (hoechster Grad, Tie-Break Name), um Edge-Inflation zu vermeiden.

// -- 0. Idempotenz: alte USES_DEVICE-Kanten entfernen (Re-Run-sicher) ---------
MATCH (:SoundRecipe)-[r:USES_DEVICE]->(:Device)
DELETE r;

// -- 1. Kanonische Device-Node je Name bestimmen + USES_DEVICE aus devices[] --
MATCH (sr:SoundRecipe)
WHERE sr.devices IS NOT NULL
UNWIND sr.devices AS dname
WITH sr, toLower(trim(dname)) AS lname
WHERE lname <> ""
MATCH (d:Device)
WHERE toLower(d.name) = lname
WITH sr, lname, d, COUNT { (d)--() } AS degree
ORDER BY degree DESC, d.name
WITH sr, lname, head(collect(d)) AS canonical
MERGE (sr)-[r:USES_DEVICE]->(canonical)
SET r.is_primary = (toLower(coalesce(sr.primary_device, "")) = lname);

// -- 2. USES_DEVICE fuer primary_device (falls nicht im Array enthalten) ------
MATCH (sr:SoundRecipe)
WHERE sr.primary_device IS NOT NULL AND trim(sr.primary_device) <> ""
WITH sr, toLower(trim(sr.primary_device)) AS lname
MATCH (d:Device)
WHERE toLower(d.name) = lname
WITH sr, d, COUNT { (d)--() } AS degree
ORDER BY degree DESC, d.name
WITH sr, head(collect(d)) AS canonical
MERGE (sr)-[r:USES_DEVICE]->(canonical)
SET r.is_primary = true;
