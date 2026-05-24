// Migration: InstrumentTemplate nodes (F10)
// Replaces hardcoded INSTRUMENT_MAP and instrument_registry.py.
// Run once via neo4j_graph.run_migration() or cypher-shell.

// ── Synthesizer — chords role ─────────────────────────────────────────────────
MERGE (:InstrumentTemplate {
    role:             "chords",
    device_name:      "Phase-4",
    uuid:             "252723bf-68a6-4ee6-81f8-95ba4d0fb467",
    midi_low:         48,   midi_high:  84,
    default_velocity: 0.65,
    genres:           ["pop", "rock", "electronic", "metal", "trap"],
    not_for:          ["jazz", "classical", "acoustic", "bossa nova"],
    moods:            ["driving", "energetic", "dark", "modern"],
    description:      "Phase modulation synth — suits electronic and rock contexts"
});

MERGE (:InstrumentTemplate {
    role:             "chords",
    device_name:      "Polysynth",
    uuid:             null,
    midi_low:         48,   midi_high:  84,
    default_velocity: 0.62,
    genres:           ["electronic", "house", "techno", "dubstep", "pop"],
    not_for:          ["jazz", "acoustic", "classical"],
    moods:            ["warm", "dark", "atmospheric", "modern"],
    description:      "Subtractive synth — pads, strings, warm chords"
});

MERGE (:InstrumentTemplate {
    role:             "chords",
    device_name:      "Polymer",
    uuid:             null,
    midi_low:         48,   midi_high:  84,
    default_velocity: 0.62,
    genres:           ["ambient", "cinematic", "new age", "electronic"],
    moods:            ["atmospheric", "evolving", "spacious"],
    description:      "Wavetable/hybrid synth — broad pads and atmospheric sounds"
});

// ── Synthesizer — lead role ───────────────────────────────────────────────────
MERGE (:InstrumentTemplate {
    role:             "lead",
    device_name:      "FM-4",
    uuid:             "7a0a94df-3aa4-4bb5-8e24-2511999871ad",
    midi_low:         55,   midi_high:  88,
    default_velocity: 0.72,
    genres:           ["electronic", "metal", "dubstep", "jazz", "rock"],
    moods:            ["bright", "aggressive", "metallic", "funky"],
    description:      "FM synthesis — characteristic metallic/bell sound"
});

MERGE (:InstrumentTemplate {
    role:             "lead",
    device_name:      "Phase-4",
    uuid:             "252723bf-68a6-4ee6-81f8-95ba4d0fb467",
    midi_low:         55,   midi_high:  96,
    default_velocity: 0.70,
    genres:           ["pop", "rock", "electronic", "trap"],
    not_for:          ["jazz", "acoustic", "classical"],
    moods:            ["bright", "cutting", "energetic"],
    description:      "Phase-4 as lead — sharp, cutting through mix"
});

MERGE (:InstrumentTemplate {
    role:             "lead",
    device_name:      "Surge XT",
    uuid:             null,
    midi_low:         48,   midi_high:  96,
    default_velocity: 0.68,
    genres:           ["rock", "metal", "cinematic", "electronic"],
    moods:            ["powerful", "rich", "complex"],
    description:      "Hybrid synth — versatile for lead and pad sounds"
});

// ── Bass role ─────────────────────────────────────────────────────────────────
MERGE (:InstrumentTemplate {
    role:             "bass",
    device_name:      "FM-4",
    uuid:             "7a0a94df-3aa4-4bb5-8e24-2511999871ad",
    midi_low:         24,   midi_high:  52,
    default_velocity: 0.80,
    genres:           ["dubstep", "drum and bass", "electronic", "neurofunk"],
    moods:            ["dark", "aggressive", "heavy"],
    description:      "FM reese bass — detuned operators, characteristic wobble"
});

MERGE (:InstrumentTemplate {
    role:             "bass",
    device_name:      "Polysynth",
    uuid:             null,
    midi_low:         24,   midi_high:  52,
    default_velocity: 0.78,
    genres:           ["house", "techno", "pop", "funk"],
    moods:            ["warm", "groovy", "driving"],
    description:      "Subtractive synth bass — punchy with LFO filter modulation"
});

// ── Drums — kick role ─────────────────────────────────────────────────────────
MERGE (:InstrumentTemplate {
    role:        "kick",
    device_name: "E-Kick",
    uuid:        null,
    midi_low:    36, midi_high: 36, default_velocity: 0.88,
    genres:      ["techno", "dubstep", "house", "electronic", "pop", "rock", "metal", "trap"],
    moods:       ["punchy", "modern", "tight"],
    description: "Electronic kick — sub-sine + pitch envelope, no sample needed"
});

// ── Drums — snare role ────────────────────────────────────────────────────────
MERGE (:InstrumentTemplate {
    role:        "snare",
    device_name: "E-Snare",
    uuid:        null,
    midi_low:    38, midi_high: 38, default_velocity: 0.82,
    genres:      ["techno", "dubstep", "house", "electronic", "pop", "rock", "metal", "trap"],
    moods:       ["punchy", "crisp", "tight"],
    description: "Electronic snare — noise + tone synthesis"
});

// ── Drums — hihat role ────────────────────────────────────────────────────────
MERGE (:InstrumentTemplate {
    role:        "hihat",
    device_name: "E-HiHat",
    uuid:        null,
    midi_low:    42, midi_high: 46, default_velocity: 0.55,
    genres:      ["techno", "dubstep", "house", "electronic", "pop", "rock", "metal", "trap"],
    moods:       ["tight", "crisp", "driving"],
    description: "Electronic hi-hat — noise + filter, open/closed control"
});

// ── Sampler ───────────────────────────────────────────────────────────────────
MERGE (:InstrumentTemplate {
    role:             "sampler",
    device_name:      "Sampler",
    uuid:             null,
    midi_low:         0,   midi_high:  127,
    default_velocity: 0.70,
    genres:           ["hip-hop", "trap", "experimental", "ambient"],
    moods:            ["textural", "organic", "lo-fi"],
    description:      "Sample-based synthesis — WAV/FLAC/AIFF, grain mode"
});

// ── Piano / organic ───────────────────────────────────────────────────────────
MERGE (:InstrumentTemplate {
    role:             "chords",
    device_name:      "Piano",
    uuid:             null,
    midi_low:         36,   midi_high:  96,
    default_velocity: 0.60,
    genres:           ["jazz", "classical", "bossa nova", "blues", "soul", "acoustic"],
    not_for:          ["metal", "trap", "dubstep"],
    moods:            ["mellow", "introspective", "warm", "organic"],
    description:      "Acoustic piano — natural sound for organic genres"
});
