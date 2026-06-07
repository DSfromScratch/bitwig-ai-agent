// Dedupliziert Device-Nodes, die sich nur in Gross-/Kleinschreibung unterscheiden
// (z.B. "Poly Grid" vs "poly grid"). Apply (Neo4j laeuft als Podman-Container):
//     podman exec -i neo4j cypher-shell -u neo4j -p neo4jllm < src/knowledge/migrations/dedup_device_nodes.cypher
// Alternativ via Python-Driver (mit Vorher/Nachher-Report + Sicherheits-Check):
//     .venv/bin/python scripts/dedup_device_nodes.py
//
// Befund (Live-Analyse): 127 Gruppen mit je 2 Varianten. Die Title-Case-Variante
// ist die kanonische (traegt in 127/127 Faellen die kuratierten Parameter sowie
// HAS_PARAMETER/SIMILAR_TO/USES/USES_DEVICE-Relationen). Die lowercase-Variante
// ist duenn (nur name + builtin_uuid) und traegt 0 Relationen — ABER ihre
// builtin_uuid (Load-Command-UUID) fehlt in 26 Faellen der Title-Variante. Diese
// UUID wird daher vor dem Loeschen via coalesce uebernommen (kein Datenverlust).
//
// HINWEIS: Der Python-Runner verweigert das Loeschen, falls (wider Erwarten)
// doch Relationen an einer lowercase-Node haengen — dann ist ein generisches
// Rewiring noetig (APOC apoc.refactor.mergeNodes). Aktuell: 0 Relationen.
//
// Idempotent: nach dem ersten Lauf existieren keine lowercase-Duplikate mehr.

// -- 1. builtin_uuid/load_cmd von der duennen lowercase- in die Title-Node ----
MATCH (lower:Device)
WHERE lower.name = toLower(lower.name)
MATCH (titled:Device)
WHERE titled.name <> lower.name
  AND toLower(trim(titled.name)) = toLower(trim(lower.name))
SET titled.builtin_uuid = coalesce(titled.builtin_uuid, lower.builtin_uuid),
    titled.load_cmd     = coalesce(titled.load_cmd, lower.load_cmd);

// -- 2. Duenne lowercase-Duplikate entfernen ---------------------------------
MATCH (lower:Device)
WHERE lower.name = toLower(lower.name)
MATCH (titled:Device)
WHERE titled.name <> lower.name
  AND toLower(trim(titled.name)) = toLower(trim(lower.name))
DETACH DELETE lower;
