// Add cross-domain relationships for richer context retrieval
// Run: source .venv/bin/activate && python scripts/run_migration.py src/knowledge/migrations/add_cross_domain_links.cypher

// ── 1. Workflow -[REQUIRES]-> Device ─────────────────────────────────────────
MATCH (w:Workflow {name: "Sidechain Kompression"}), (d:Device {name: "Compressor"})
MERGE (w)-[:REQUIRES]->(d);

MATCH (w:Workflow {name: "Mastering Chain"}), (d:Device {name: "EQ-5"})
MERGE (w)-[:REQUIRES]->(d);

MATCH (w:Workflow {name: "Mastering Chain"}), (d:Device {name: "Compressor"})
MERGE (w)-[:REQUIRES]->(d);

MATCH (w:Workflow {name: "Mastering Chain"}), (d:Device {name: "Limiter"})
MERGE (w)-[:REQUIRES]->(d);

MATCH (w:Workflow {name: "Dubstep Reese Bass"}), (d:Device {name: "FM-4"})
MERGE (w)-[:REQUIRES]->(d);

MATCH (w:Workflow {name: "Dubstep Reese Bass"}), (d:Device {name: "Ladder Filter"})
MERGE (w)-[:REQUIRES]->(d);

MATCH (w:Workflow {name: "Dubstep Half-Time Drums"}), (d:Device {name: "Drum Machine"})
MERGE (w)-[:REQUIRES]->(d);

MATCH (w:Workflow {name: "Dubstep Half-Time Drums"}), (d:Device {name: "Transient Control"})
MERGE (w)-[:REQUIRES]->(d);

// ── 2. Workflow -[USES_COMMAND]-> OscCommand ─────────────────────────────────
MATCH (w:Workflow {name: "Sidechain Kompression"}), (o:OscCommand {address: "/track/add/instrument"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Sidechain Kompression"}), (o:OscCommand {address: "/browser/fx/load"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Sidechain Kompression"}), (o:OscCommand {address: "/device/param/named"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Mastering Chain"}), (o:OscCommand {address: "/track/add/instrument"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Mastering Chain"}), (o:OscCommand {address: "/browser/fx/load"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Mastering Chain"}), (o:OscCommand {address: "/eq/freq/{b}"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Mastering Chain"}), (o:OscCommand {address: "/eq/gain/{b}"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Mastering Chain"}), (o:OscCommand {address: "/device/param/named"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Dubstep Reese Bass"}), (o:OscCommand {address: "/track/add/instrument"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Dubstep Reese Bass"}), (o:OscCommand {address: "/browser/device/load"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Dubstep Reese Bass"}), (o:OscCommand {address: "/device/param/named"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Dubstep Half-Time Drums"}), (o:OscCommand {address: "/track/add/instrument"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Dubstep Half-Time Drums"}), (o:OscCommand {address: "/browser/device/load"})
MERGE (w)-[:USES_COMMAND]->(o);

MATCH (w:Workflow {name: "Dubstep Half-Time Drums"}), (o:OscCommand {address: "/device/param/named"})
MERGE (w)-[:USES_COMMAND]->(o);

// ── 3. Device -[LOADED_VIA]-> OscCommand ─────────────────────────────────────
// Synth instruments → /browser/device/load
MATCH (d:Device {name: "Phase-4"}),  (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "FM-4"}),     (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Polysynth"}),(o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Polymer"}),  (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Surge XT"}), (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Drum Machine"}), (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "v9 Kick"}),  (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "v9 Snare"}), (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "v9 Hat Closed"}), (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "v9 Clap"}),  (o:OscCommand {address: "/browser/device/load"}) MERGE (d)-[:LOADED_VIA]->(o);

// FX devices → /browser/fx/load
MATCH (d:Device {name: "Reverb"}),           (o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Delay-2"}),          (o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "EQ-5"}),             (o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Compressor"}),       (o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Transient Control"}),(o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Distortion"}),       (o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Ladder Filter"}),    (o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Limiter"}),          (o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "Saturator"}),        (o:OscCommand {address: "/browser/fx/load"}) MERGE (d)-[:LOADED_VIA]->(o);

// Sampler → /sampler/load
MATCH (d:Device {name: "Sampler"}), (o:OscCommand {address: "/sampler/load"}) MERGE (d)-[:LOADED_VIA]->(o);

// EQ-5 also uses eq-specific commands
MATCH (d:Device {name: "EQ-5"}), (o:OscCommand {address: "/eq/freq/{b}"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "EQ-5"}), (o:OscCommand {address: "/eq/gain/{b}"}) MERGE (d)-[:LOADED_VIA]->(o);
MATCH (d:Device {name: "EQ-5"}), (o:OscCommand {address: "/eq/q/{b}"})    MERGE (d)-[:LOADED_VIA]->(o);

// ── 4. Sound -[ACHIEVED_BY]-> Workflow ───────────────────────────────────────
MATCH (s:Sound {name: "Reese Bass"}),      (w:Workflow {name: "Dubstep Reese Bass"})     MERGE (s)-[:ACHIEVED_BY]->(w);
MATCH (s:Sound {name: "Half-Time Snare"}), (w:Workflow {name: "Dubstep Half-Time Drums"}) MERGE (s)-[:ACHIEVED_BY]->(w);
MATCH (s:Sound {name: "Techno Kick"}),     (w:Workflow {name: "Dubstep Half-Time Drums"}) MERGE (s)-[:ACHIEVED_BY]->(w);
