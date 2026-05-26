// Fix wrong Device node names → correct Bitwig internal names
// Run once: python -c "from src.knowledge.neo4j_graph import session; s=session().__enter__(); s.run(open('src/knowledge/migrations/fix_device_names.cypher').read())"

// Rename Device nodes
MATCH (d:Device {name: "E-Kick"})   SET d.name = "v9 Kick";
MATCH (d:Device {name: "E-Snare"})  SET d.name = "v9 Snare";
MATCH (d:Device {name: "E-HiHat"})  SET d.name = "v9 Hat Closed";
MATCH (d:Device {name: "E-Clap"})   SET d.name = "v9 Clap";
MATCH (d:Device {name: "E-Tom"})    SET d.name = "v9 Tom";
