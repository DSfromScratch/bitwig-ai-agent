// Migration: DrumPattern, DrumSound, VelocityProfile nodes (F9)
// Replaces DRUM_PROFILES Python dict in song_tools.py.
// Run once against a live Neo4j instance via cypher-shell or neo4j_graph.run_migration().

// ── DrumSound (GM pitch mapping) ─────────────────────────────────────────────
MERGE (:DrumSound {name: "kick",       gm_pitch: 36, description: "Bass Drum 1"});
MERGE (:DrumSound {name: "snare",      gm_pitch: 38, description: "Acoustic Snare"});
MERGE (:DrumSound {name: "closed_hat", gm_pitch: 42, description: "Closed Hi-Hat"});
MERGE (:DrumSound {name: "open_hat",   gm_pitch: 46, description: "Open Hi-Hat"});
MERGE (:DrumSound {name: "crash",      gm_pitch: 49, description: "Crash Cymbal 1"});

// ── VelocityProfile ───────────────────────────────────────────────────────────
MERGE (:VelocityProfile {
    context:     "aggressive_chorus",
    kick_vel:    0.95,
    snare_vel:   0.92,
    ghost_ratio: 0.48,
    description: "High energy, punchy — metal/hard rock chorus"
});
MERGE (:VelocityProfile {
    context:     "mellow_verse",
    kick_vel:    0.65,
    snare_vel:   0.60,
    ghost_ratio: 0.70,
    description: "Soft, organic — acoustic/introspective"
});

// ── pop ───────────────────────────────────────────────────────────────────────
MERGE (:DrumPattern {genre:"pop", section:"intro",
    kick_beats:  [0.0, 4.0],    snare_beats: [4.0],
    hat_step:    1.0,  hat_vel_on: 0.40, hat_vel_off: 0.30,
    kick_vel:    0.70, snare_vel:  0.65,
    energy:      0.40, mood: "light",
    description: "Sparse pop intro — quarter-note hat, minimal kick"});

MERGE (:DrumPattern {genre:"pop", section:"verse",
    kick_beats:  [0.0, 2.0, 4.0, 6.0], snare_beats: [2.0, 6.0],
    hat_step:    0.5,  hat_vel_on: 0.52, hat_vel_off: 0.38,
    kick_vel:    0.88, snare_vel:  0.82,
    energy:      0.70, mood: "driving",
    description: "Standard pop verse — 8th-note hat, straight kick/snare"});

MERGE (:DrumPattern {genre:"pop", section:"chorus",
    kick_beats:  "4floor", snare_beats: [2.0, 6.0],
    hat_step:    0.25, hat_vel_on: 0.62, hat_vel_off: 0.42,
    kick_vel:    0.95, snare_vel:  0.92,
    energy:      0.92, mood: "energetic",
    description: "4-on-the-floor chorus — 16th-note hat, peak energy"});

MERGE (:DrumPattern {genre:"pop", section:"solo",
    kick_beats:  [0.0, 2.0, 4.0, 6.0], snare_beats: [2.0, 6.0],
    hat_step:    1.0,  hat_vel_on: 0.40, hat_vel_off: 0.30,
    kick_vel:    0.82, snare_vel:  0.78,
    energy:      0.65, mood: "driving",
    description: "Pop solo — quarter-note hat to support melody"});

MERGE (:DrumPattern {genre:"pop", section:"outro",
    kick_beats:  [0.0, 4.0], snare_beats: [2.0],
    hat_step:    1.0,  hat_vel_on: 0.35, hat_vel_off: 0.25,
    kick_vel:    0.72, snare_vel:  0.68,
    energy:      0.30, mood: "light",
    description: "Pop outro — fading energy, sparse pattern"});

// ── jazz ──────────────────────────────────────────────────────────────────────
MERGE (:DrumPattern {genre:"jazz", section:"intro",
    kick_beats:  [0.0], snare_beats: [],
    hat_step:    0.67, hat_vel_on: 0.35, hat_vel_off: 0.22,
    kick_vel:    0.60, snare_vel:  0.50,
    energy:      0.30, mood: "introspective",
    description: "Jazz intro — triplet ride feel, sparse kick"});

MERGE (:DrumPattern {genre:"jazz", section:"verse",
    kick_beats:  [0.0, 3.0], snare_beats: [2.0, 6.0],
    hat_step:    0.67, hat_vel_on: 0.45, hat_vel_off: 0.28,
    kick_vel:    0.72, snare_vel:  0.68,
    energy:      0.55, mood: "warm",
    description: "Jazz verse — swing triplet hat, ghost snares"});

MERGE (:DrumPattern {genre:"jazz", section:"chorus",
    kick_beats:  [0.0, 2.0, 4.0, 6.0], snare_beats: [2.0, 6.0],
    hat_step:    0.5,  hat_vel_on: 0.52, hat_vel_off: 0.35,
    kick_vel:    0.82, snare_vel:  0.78,
    energy:      0.72, mood: "warm",
    description: "Jazz chorus — straight feel, more open hat"});

MERGE (:DrumPattern {genre:"jazz", section:"solo",
    kick_beats:  [0.0, 2.5], snare_beats: [2.0, 6.0],
    hat_step:    0.67, hat_vel_on: 0.42, hat_vel_off: 0.28,
    kick_vel:    0.75, snare_vel:  0.70,
    energy:      0.60, mood: "warm",
    description: "Jazz solo — triplet feel behind the soloist"});

MERGE (:DrumPattern {genre:"jazz", section:"outro",
    kick_beats:  [0.0], snare_beats: [2.0],
    hat_step:    1.0,  hat_vel_on: 0.30, hat_vel_off: 0.22,
    kick_vel:    0.55, snare_vel:  0.50,
    energy:      0.25, mood: "introspective",
    description: "Jazz outro — quiet, minimal, resolving"});

// ── metal ─────────────────────────────────────────────────────────────────────
MERGE (:DrumPattern {genre:"metal", section:"intro",
    kick_beats:  [0.0,0.5,1.0,1.5,2.0,2.5,3.0,3.5], snare_beats: [2.0, 6.0],
    hat_step:    0.25, hat_vel_on: 0.55, hat_vel_off: 0.40,
    kick_vel:    0.88, snare_vel:  0.85,
    energy:      0.80, mood: "aggressive",
    description: "Metal intro — 8th-note kick pattern, 16th hat"});

MERGE (:DrumPattern {genre:"metal", section:"verse",
    kick_beats:  "double", snare_beats: [2.0, 6.0],
    hat_step:    0.25, hat_vel_on: 0.65, hat_vel_off: 0.45,
    kick_vel:    0.95, snare_vel:  0.90,
    energy:      0.90, mood: "aggressive",
    description: "Metal verse — double kick, 16th-note hat, powerful"});

MERGE (:DrumPattern {genre:"metal", section:"chorus",
    kick_beats:  "double", snare_beats: [2.0, 4.0, 6.0],
    hat_step:    0.25, hat_vel_on: 0.68, hat_vel_off: 0.48,
    kick_vel:    0.98, snare_vel:  0.95,
    energy:      0.98, mood: "aggressive",
    description: "Metal chorus — max energy, extra snare hit on beat 4"});

MERGE (:DrumPattern {genre:"metal", section:"solo",
    kick_beats:  "double", snare_beats: [2.0, 6.0],
    hat_step:    0.5,  hat_vel_on: 0.55, hat_vel_off: 0.38,
    kick_vel:    0.92, snare_vel:  0.82,
    energy:      0.85, mood: "aggressive",
    description: "Metal solo — double kick, 8th hat to support lead"});

MERGE (:DrumPattern {genre:"metal", section:"outro",
    kick_beats:  [0.0, 2.0], snare_beats: [2.0],
    hat_step:    0.5,  hat_vel_on: 0.45, hat_vel_off: 0.32,
    kick_vel:    0.75, snare_vel:  0.65,
    energy:      0.55, mood: "driving",
    description: "Metal outro — pulling back, half-time feel"});

// ── trap ──────────────────────────────────────────────────────────────────────
MERGE (:DrumPattern {genre:"trap", section:"intro",
    kick_beats:  [0.0, 1.5, 3.0], snare_beats: [],
    hat_step:    0.125, hat_vel_on: 0.35, hat_vel_off: 0.20,
    kick_vel:    0.72,  snare_vel:  0.65,
    energy:      0.40,  mood: "dark",
    description: "Trap intro — 32nd-note hat rolls, syncopated kick"});

MERGE (:DrumPattern {genre:"trap", section:"verse",
    kick_beats:  [0.0, 1.5, 3.0, 4.5], snare_beats: [2.0, 6.0],
    hat_step:    0.125, hat_vel_on: 0.55, hat_vel_off: 0.28,
    kick_vel:    0.85,  snare_vel:  0.80,
    energy:      0.72,  mood: "dark",
    description: "Trap verse — hi-hat rolls, slow snare, 808 kick"});

MERGE (:DrumPattern {genre:"trap", section:"chorus",
    kick_beats:  [0.0, 1.0, 2.5, 4.0, 5.5], snare_beats: [2.0, 6.0],
    hat_step:    0.125, hat_vel_on: 0.60, hat_vel_off: 0.32,
    kick_vel:    0.90,  snare_vel:  0.85,
    energy:      0.88,  mood: "dark",
    description: "Trap chorus — busier kick, intense hat rolls"});

MERGE (:DrumPattern {genre:"trap", section:"solo",
    kick_beats:  [0.0, 2.0, 3.5], snare_beats: [2.0, 6.0],
    hat_step:    0.125, hat_vel_on: 0.50, hat_vel_off: 0.25,
    kick_vel:    0.80,  snare_vel:  0.75,
    energy:      0.65,  mood: "dark",
    description: "Trap solo — moderate energy, steady hat"});

MERGE (:DrumPattern {genre:"trap", section:"outro",
    kick_beats:  [0.0, 3.0], snare_beats: [4.0],
    hat_step:    0.25,  hat_vel_on: 0.35, hat_vel_off: 0.22,
    kick_vel:    0.65,  snare_vel:  0.55,
    energy:      0.30,  mood: "dark",
    description: "Trap outro — sparse, fading"});

// ── bossa nova ────────────────────────────────────────────────────────────────
MERGE (:DrumPattern {genre:"bossa nova", section:"intro",
    kick_beats:  [0.0, 1.5, 2.5], snare_beats: [],
    hat_step:    0.5,  hat_vel_on: 0.30, hat_vel_off: 0.20,
    kick_vel:    0.60, snare_vel:  0.50,
    energy:      0.35, mood: "mellow",
    description: "Bossa intro — gentle syncopated kick, light hat"});

MERGE (:DrumPattern {genre:"bossa nova", section:"verse",
    kick_beats:  [0.0, 1.5, 2.5, 4.0, 5.5, 6.5], snare_beats: [2.0, 6.0],
    hat_step:    0.5,  hat_vel_on: 0.40, hat_vel_off: 0.28,
    kick_vel:    0.72, snare_vel:  0.65,
    energy:      0.55, mood: "mellow",
    description: "Bossa verse — classic samba-feel kick pattern"});

MERGE (:DrumPattern {genre:"bossa nova", section:"chorus",
    kick_beats:  [0.0, 1.5, 2.5, 4.0, 5.5, 6.5], snare_beats: [2.0, 6.0],
    hat_step:    0.5,  hat_vel_on: 0.45, hat_vel_off: 0.32,
    kick_vel:    0.78, snare_vel:  0.72,
    energy:      0.65, mood: "mellow",
    description: "Bossa chorus — slightly more energy, same samba feel"});

MERGE (:DrumPattern {genre:"bossa nova", section:"solo",
    kick_beats:  [0.0, 1.5, 2.5, 4.0], snare_beats: [2.0, 6.0],
    hat_step:    0.5,  hat_vel_on: 0.38, hat_vel_off: 0.25,
    kick_vel:    0.70, snare_vel:  0.65,
    energy:      0.55, mood: "mellow",
    description: "Bossa solo — supporting sparse kit behind lead"});

MERGE (:DrumPattern {genre:"bossa nova", section:"outro",
    kick_beats:  [0.0, 2.5], snare_beats: [2.0],
    hat_step:    1.0,  hat_vel_on: 0.28, hat_vel_off: 0.18,
    kick_vel:    0.55, snare_vel:  0.48,
    energy:      0.25, mood: "mellow",
    description: "Bossa outro — minimal, gentle resolution"});

// ── rock (alias: same as pop with slightly higher energy) ─────────────────────
MERGE (:DrumPattern {genre:"rock", section:"intro",
    kick_beats:  [0.0, 4.0],    snare_beats: [4.0],
    hat_step:    1.0,  hat_vel_on: 0.45, hat_vel_off: 0.32,
    kick_vel:    0.75, snare_vel:  0.70,
    energy:      0.45, mood: "driving",
    description: "Rock intro — sparse, building energy"});

MERGE (:DrumPattern {genre:"rock", section:"verse",
    kick_beats:  [0.0, 2.0, 4.0, 6.0], snare_beats: [2.0, 6.0],
    hat_step:    0.5,  hat_vel_on: 0.55, hat_vel_off: 0.40,
    kick_vel:    0.88, snare_vel:  0.82,
    energy:      0.72, mood: "driving",
    description: "Straight rock beat, moderate energy, 8th-note hat"});

MERGE (:DrumPattern {genre:"rock", section:"chorus",
    kick_beats:  "4floor", snare_beats: [2.0, 6.0],
    hat_step:    0.25, hat_vel_on: 0.65, hat_vel_off: 0.45,
    kick_vel:    0.95, snare_vel:  0.92,
    energy:      0.92, mood: "energetic",
    description: "4-on-the-floor kick, 16th-note hat — peak energy"});

MERGE (:DrumPattern {genre:"rock", section:"solo",
    kick_beats:  [0.0, 2.0, 4.0, 6.0], snare_beats: [2.0, 6.0],
    hat_step:    0.5,  hat_vel_on: 0.45, hat_vel_off: 0.32,
    kick_vel:    0.85, snare_vel:  0.80,
    energy:      0.75, mood: "driving",
    description: "Rock solo support — steady groove behind guitar"});

MERGE (:DrumPattern {genre:"rock", section:"outro",
    kick_beats:  [0.0, 4.0], snare_beats: [2.0],
    hat_step:    1.0,  hat_vel_on: 0.38, hat_vel_off: 0.28,
    kick_vel:    0.75, snare_vel:  0.70,
    energy:      0.35, mood: "driving",
    description: "Rock outro — half-time, resolving"});
