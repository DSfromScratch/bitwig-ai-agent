"""
Neo4j Wissensgraph für Bitwig Studio 6.

Schema-Überblick:
  (Genre)      -[:USES]->          (Device)
  (Device)     -[:HAS_PARAMETER]-> (Parameter)
  (Device)     -[:RECOMMENDED_WITH]-> (Device)
  (Sound)      -[:CREATED_BY]->    (Device)
  (Genre)      -[:TYPICAL_SOUND]-> (Sound)
  (Workflow)   -[:USES_DEVICE]->   (Device)
  (Song)       -[:CLASSIFIED_AS]-> (Genre)
  (Song)       -[:HAS_STEM]->      (Stem)
  (Preset)     -[:BELONGS_TO]->    (Device)
  (Pattern)    -[:USED_IN]->       (Genre)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from neo4j import GraphDatabase

# ── Verbindung ────────────────────────────────────────────────────────────────

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jllm")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

_driver = None
_neo4j_available: bool | None = None  # None = ungeprüft


def reset_availability_cache() -> None:
    """Setzt den Neo4j-Verfügbarkeits-Cache zurück (für Tests und env-Wechsel)."""
    global _neo4j_available, _driver
    _neo4j_available = None
    _driver = None


def is_available() -> bool:
    """Gibt True zurück wenn Neo4j erreichbar ist (gecacht nach erstem Check)."""
    global _neo4j_available
    if _neo4j_available is not None:
        return _neo4j_available
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session(database=NEO4J_DATABASE) as s:
            s.run("RETURN 1").single()
        driver.close()
        _neo4j_available = True
    except Exception:
        _neo4j_available = False
    return _neo4j_available


def get_driver():
    global _driver
    if not is_available():
        raise ConnectionError(
            f"Neo4j nicht erreichbar ({NEO4J_URI}). "
            "Starte Neo4j oder setze NEO4J_URI auf einen laufenden Server."
        )
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver

@contextmanager
def session():
    with get_driver().session(database=NEO4J_DATABASE) as s:
        yield s

# ── Schema ────────────────────────────────────────────────────────────────────

SCHEMA_CONSTRAINTS = [
    "CREATE CONSTRAINT genre_name IF NOT EXISTS FOR (g:Genre) REQUIRE g.name IS UNIQUE",
    "CREATE CONSTRAINT device_name IF NOT EXISTS FOR (d:Device) REQUIRE d.name IS UNIQUE",
    "CREATE CONSTRAINT sound_name  IF NOT EXISTS FOR (s:Sound)  REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT workflow_name IF NOT EXISTS FOR (w:Workflow) REQUIRE w.name IS UNIQUE",
    "CREATE CONSTRAINT pattern_name  IF NOT EXISTS FOR (p:Pattern)  REQUIRE p.name IS UNIQUE",
]

def create_schema():
    with session() as s:
        for c in SCHEMA_CONSTRAINTS:
            try:
                s.run(c)
            except Exception:
                pass
    print("✓ Schema-Constraints erstellt")

# ── Bitwig Studio 6 — Vollständige Gerätedaten ───────────────────────────────

DEVICES = [
    # ── Synthesizer ──────────────────────────────────────────────────────────
    {"name": "Phase-4",    "type": "instrument", "category": "synthesizer",
     "description": "4-Operator Phasenmodulations-Synthesizer. Leads, Bässe, komplexe Texturen.",
     "browser_path": "Instruments > Synthesizers > Phase-4",
     "params": [
         {"name": "Osc1 Wave",    "type": "enum",  "values": "Saw,Square,Sine,Triangle", "default": "Saw"},
         {"name": "Osc2 Wave",    "type": "enum",  "values": "Saw,Square,Sine,Triangle", "default": "Square"},
         {"name": "Phase Mod",    "type": "float", "min": 0.0,  "max": 1.0,   "default": 0.0},
         {"name": "Filter Cutoff","type": "float", "min": 20.0, "max": 20000.0,"default": 8000.0, "unit": "Hz"},
         {"name": "Filter Res",   "type": "float", "min": 0.0,  "max": 1.0,   "default": 0.2},
         {"name": "Env Attack",   "type": "float", "min": 0.0,  "max": 10.0,  "default": 0.01, "unit": "s"},
         {"name": "Env Decay",    "type": "float", "min": 0.0,  "max": 10.0,  "default": 0.3,  "unit": "s"},
         {"name": "Env Sustain",  "type": "float", "min": 0.0,  "max": 1.0,   "default": 0.7},
         {"name": "Env Release",  "type": "float", "min": 0.0,  "max": 10.0,  "default": 0.5,  "unit": "s"},
     ]},

    {"name": "FM-4",       "type": "instrument", "category": "synthesizer",
     "description": "4-Operator FM-Synthesizer. Reese-Bass, metallische Sounds, E-Piano.",
     "browser_path": "Instruments > Synthesizers > FM-4",
     "params": [
         {"name": "Algorithm",    "type": "int",   "min": 1,    "max": 11,    "default": 1},
         {"name": "Op1 Ratio",    "type": "float", "min": 0.5,  "max": 16.0,  "default": 1.0},
         {"name": "Op2 Ratio",    "type": "float", "min": 0.5,  "max": 16.0,  "default": 1.0},
         {"name": "Op3 Ratio",    "type": "float", "min": 0.5,  "max": 16.0,  "default": 1.0},
         {"name": "Op4 Ratio",    "type": "float", "min": 0.5,  "max": 16.0,  "default": 1.0},
         {"name": "Op1 Detune",   "type": "float", "min": -100.0,"max": 100.0,"default": 0.0, "unit": "cents"},
         {"name": "Op2 Detune",   "type": "float", "min": -100.0,"max": 100.0,"default": 0.0, "unit": "cents"},
         {"name": "Feedback",     "type": "float", "min": 0.0,  "max": 1.0,   "default": 0.0},
         {"name": "Op1 Level",    "type": "float", "min": 0.0,  "max": 1.0,   "default": 1.0},
     ]},

    {"name": "Polysynth",  "type": "instrument", "category": "synthesizer",
     "description": "Klassischer subtraktiver Synthesizer. Pads, Leads, Strings.",
     "browser_path": "Instruments > Synthesizers > Polysynth",
     "params": [
         {"name": "Osc1 Wave",    "type": "enum",  "values": "Saw,Square,Sine,Triangle,Noise"},
         {"name": "Osc2 Wave",    "type": "enum",  "values": "Saw,Square,Sine,Triangle,Noise"},
         {"name": "Osc2 Detune",  "type": "float", "min": -24.0,"max": 24.0,  "default": 0.0, "unit": "semitones"},
         {"name": "Filter Type",  "type": "enum",  "values": "Ladder LP,SVF LP,SVF HP,SVF BP"},
         {"name": "Filter Cutoff","type": "float", "min": 20.0, "max": 20000.0,"default": 5000.0},
         {"name": "Filter Res",   "type": "float", "min": 0.0,  "max": 1.0,   "default": 0.1},
         {"name": "Attack",       "type": "float", "min": 0.0,  "max": 10.0,  "default": 0.01},
         {"name": "Release",      "type": "float", "min": 0.0,  "max": 10.0,  "default": 0.5},
     ]},

    {"name": "Polymer",    "type": "instrument", "category": "synthesizer",
     "description": "Hybrid: VA + Wavetable + FM + Sample. Vielseitig.",
     "browser_path": "Instruments > Synthesizers > Polymer",
     "params": [
         {"name": "Mode",         "type": "enum",  "values": "VA,Wavetable,FM,Sample"},
         {"name": "Filter Cutoff","type": "float", "min": 20.0, "max": 20000.0,"default": 8000.0},
         {"name": "LFO Rate",     "type": "float", "min": 0.01, "max": 20.0,  "default": 1.0, "unit": "Hz"},
         {"name": "LFO Amount",   "type": "float", "min": 0.0,  "max": 1.0,   "default": 0.0},
     ]},

    {"name": "Surge XT",   "type": "instrument", "category": "synthesizer",
     "description": "Professioneller Synth, 2000+ Presets, 14 Oszillator-Typen.",
     "browser_path": "Instruments > Synthesizers > Surge XT",
     "params": [
         {"name": "Scene A Osc1 Type","type": "enum","values": "Classic,Wavetable,Window,Sine,FM2,FM3,String,Twist"},
         {"name": "Filter 1 Type",    "type": "enum","values": "LP 12,LP 24,HP 12,HP 24,BP,Notch"},
         {"name": "Filter 1 Cutoff",  "type": "float","min": 0.0,"max": 1.0,"default": 0.7},
     ]},

    # ── Drum-Synthesizer ─────────────────────────────────────────────────────
    {"name": "E-Kick",     "type": "instrument", "category": "drum_synth",
     "description": "Elektronischer Kick. Sub-Sine + Pitch-Envelope. Kein Sample nötig.",
     "browser_path": "Instruments > Drums > E-Kick",
     "params": [
         {"name": "Tune",     "type": "float", "min": -36.0,"max": 12.0, "default": 0.0,  "unit": "semitones"},
         {"name": "Punch",    "type": "float", "min": 0.0,  "max": 1.0,  "default": 0.5},
         {"name": "Decay",    "type": "float", "min": 0.01, "max": 2.0,  "default": 0.4,  "unit": "s"},
         {"name": "Sub Level","type": "float", "min": 0.0,  "max": 1.0,  "default": 0.8},
         {"name": "Click",    "type": "float", "min": 0.0,  "max": 1.0,  "default": 0.3},
     ]},

    {"name": "E-Snare",    "type": "instrument", "category": "drum_synth",
     "description": "Elektronische Snare. Noise + Tone.",
     "browser_path": "Instruments > Drums > E-Snare",
     "params": [
         {"name": "Tune",         "type": "float","min": -24.0,"max": 12.0,"default": 0.0},
         {"name": "Noise Amount", "type": "float","min": 0.0,  "max": 1.0, "default": 0.6},
         {"name": "Tone",         "type": "float","min": 0.0,  "max": 1.0, "default": 0.4},
         {"name": "Decay",        "type": "float","min": 0.01, "max": 1.0, "default": 0.25},
     ]},

    {"name": "E-HiHat",    "type": "instrument", "category": "drum_synth",
     "description": "Elektronisches Hi-Hat. Noise + Filter.",
     "browser_path": "Instruments > Drums > E-HiHat",
     "params": [
         {"name": "Tune",     "type": "float","min": -24.0,"max": 12.0,"default": 0.0},
         {"name": "Decay",    "type": "float","min": 0.001,"max": 0.5, "default": 0.05},
         {"name": "Open",     "type": "float","min": 0.0,  "max": 1.0, "default": 0.0},
         {"name": "Filter",   "type": "float","min": 0.0,  "max": 1.0, "default": 0.7},
     ]},

    {"name": "E-Clap",     "type": "instrument", "category": "drum_synth",
     "description": "Elektronischer Clap.",
     "browser_path": "Instruments > Drums > E-Clap",
     "params": [
         {"name": "Spread",   "type": "float","min": 0.0,"max": 1.0,"default": 0.5},
         {"name": "Decay",    "type": "float","min": 0.01,"max": 1.0,"default": 0.2},
     ]},

    # ── Audio Loops (virtuelle Devices — repräsentieren WAV-Loops aus installierten Paketen) ──
    {"name": "AudioLoop_GuitarRiff",  "type": "instrument", "category": "audio_loop",
     "description": "Echter E-Gitarren-Riff Loop (WAV). Rock, Metal, Blues. Laden via find_guitar_loops + load_guitar_loop.",
     "browser_path": "AudioLoop", "params": []},
    {"name": "AudioLoop_GuitarLead",  "type": "instrument", "category": "audio_loop",
     "description": "Echter E-Gitarren-Lead Loop (WAV). Rock, Metal, Blues Solo.",
     "browser_path": "AudioLoop", "params": []},
    {"name": "AudioLoop_BassGuitar",  "type": "instrument", "category": "audio_loop",
     "description": "Echter Bass-Gitarren Loop (WAV). Rock, Metal, Blues.",
     "browser_path": "AudioLoop", "params": []},

    {"name": "Drum Machine","type": "instrument", "category": "sampler",
     "description": "16-Pad Drum Machine. Jedes Pad: eigenes Instrument/Sample.",
     "browser_path": "Instruments > Drum Machine",
     "params": []},

    {"name": "Sampler",    "type": "instrument", "category": "sampler",
     "description": "Sample-basierter Synthesizer. WAV/FLAC/AIFF. Grain-Mode.",
     "browser_path": "Instruments > Sampler",
     "params": [
         {"name": "Tune",        "type": "float","min": -48.0,"max": 48.0,"default": 0.0},
         {"name": "Loop Mode",   "type": "enum", "values": "Off,Forward,PingPong"},
         {"name": "Grain Size",  "type": "float","min": 0.01, "max": 1.0, "default": 0.1},
     ]},

    # ── Effekte ──────────────────────────────────────────────────────────────
    {"name": "Compressor", "type": "effect", "category": "dynamics",
     "description": "Dynamik-Kompressor. Peak/RMS. Sidechain-fähig.",
     "browser_path": "Devices > Audio FX > Dynamics > Compressor",
     "params": [
         {"name": "Threshold",  "type": "float","min": -60.0,"max": 0.0, "default": -18.0,"unit": "dB"},
         {"name": "Ratio",      "type": "float","min": 1.0,  "max": 100.0,"default": 4.0},
         {"name": "Attack",     "type": "float","min": 0.01, "max": 500.0,"default": 5.0,  "unit": "ms"},
         {"name": "Release",    "type": "float","min": 1.0,  "max": 2000.0,"default": 80.0,"unit": "ms"},
         {"name": "Makeup Gain","type": "float","min": 0.0,  "max": 24.0, "default": 0.0,  "unit": "dB"},
     ]},

    {"name": "Limiter",    "type": "effect", "category": "dynamics",
     "description": "Brickwall-Limiter. True-Peak Detection.",
     "browser_path": "Devices > Audio FX > Dynamics > Limiter",
     "params": [
         {"name": "Ceiling",    "type": "float","min": -12.0,"max": 0.0,"default": -0.3,"unit": "dBTP"},
         {"name": "Lookahead",  "type": "float","min": 0.0,  "max": 10.0,"default": 1.0, "unit": "ms"},
     ]},

    {"name": "EQ-5",       "type": "effect", "category": "eq",
     "description": "5-Band parametrischer EQ. HPF, Low Shelf, 3× Peak, High Shelf, LPF.",
     "browser_path": "Devices > Audio FX > EQ > EQ-5",
     "params": [
         {"name": "Band1 Freq", "type": "float","min": 20.0,  "max": 20000.0,"default": 80.0},
         {"name": "Band1 Gain", "type": "float","min": -24.0, "max": 24.0,   "default": 0.0},
         {"name": "Band3 Freq", "type": "float","min": 200.0, "max": 5000.0, "default": 500.0},
         {"name": "Band3 Gain", "type": "float","min": -24.0, "max": 24.0,   "default": 0.0},
         {"name": "Band3 Q",    "type": "float","min": 0.1,   "max": 10.0,   "default": 1.0},
     ]},

    {"name": "Distortion", "type": "effect", "category": "saturation",
     "description": "Verzerrer. Soft/Hard Clip, Fold, Wrap.",
     "browser_path": "Devices > Audio FX > Distortion > Distortion",
     "params": [
         {"name": "Mode",   "type": "enum", "values": "Soft Clip,Hard Clip,Fold,Wrap,Tube"},
         {"name": "Drive",  "type": "float","min": 0.0,"max": 1.0,"default": 0.3},
         {"name": "Tone",   "type": "float","min": 0.0,"max": 1.0,"default": 0.5},
     ]},

    {"name": "Saturator",  "type": "effect", "category": "saturation",
     "description": "Soft-Clipper / Sättiger. Wärme und Obertöne.",
     "browser_path": "Devices > Audio FX > Distortion > Saturator",
     "params": [
         {"name": "Drive",     "type": "float","min": 0.0,"max": 1.0,"default": 0.2},
         {"name": "Output",    "type": "float","min": 0.0,"max": 2.0,"default": 1.0},
     ]},

    {"name": "Reverb",     "type": "effect", "category": "time",
     "description": "Algorithmischer Hall. Room, Hall, Plate.",
     "browser_path": "Devices > Audio FX > Reverb > Reverb",
     "params": [
         {"name": "Pre-Delay","type": "float","min": 0.0,  "max": 500.0,"default": 20.0,"unit": "ms"},
         {"name": "Size",     "type": "float","min": 0.0,  "max": 1.0,  "default": 0.5},
         {"name": "Decay",    "type": "float","min": 0.1,  "max": 30.0, "default": 2.0,  "unit": "s"},
         {"name": "Mix",      "type": "float","min": 0.0,  "max": 1.0,  "default": 0.3},
     ]},

    {"name": "Delay-2",    "type": "effect", "category": "time",
     "description": "Stereo-Delay. Sync-Option.",
     "browser_path": "Devices > Audio FX > Delay > Delay-2",
     "params": [
         {"name": "Time L",   "type": "float","min": 1.0,  "max": 4000.0,"default": 375.0,"unit": "ms"},
         {"name": "Feedback", "type": "float","min": 0.0,  "max": 1.0,   "default": 0.4},
         {"name": "Mix",      "type": "float","min": 0.0,  "max": 1.0,   "default": 0.25},
     ]},

    {"name": "Ladder Filter","type": "effect","category": "filter",
     "description": "Moog-style Ladder-Filter. Klassischer analoger Charakter.",
     "browser_path": "Devices > Audio FX > Filter > Ladder Filter",
     "params": [
         {"name": "Cutoff",   "type": "float","min": 20.0, "max": 20000.0,"default": 1000.0,"unit": "Hz"},
         {"name": "Resonance","type": "float","min": 0.0,  "max": 1.0,   "default": 0.3},
         {"name": "Drive",    "type": "float","min": 0.0,  "max": 1.0,   "default": 0.0},
     ]},

    {"name": "Transient Control","type": "effect","category": "dynamics",
     "description": "Attack/Sustain Shaper für Drums und Percussion.",
     "browser_path": "Devices > Audio FX > Dynamics > Transient Control",
     "params": [
         {"name": "Attack",   "type": "float","min": -1.0,"max": 1.0,"default": 0.0},
         {"name": "Sustain",  "type": "float","min": -1.0,"max": 1.0,"default": 0.0},
     ]},
]

# ── Genre-Daten ───────────────────────────────────────────────────────────────

GENRES = [
    {"name": "Dubstep",          "bpm_min": 135, "bpm_max": 150, "key_mode": "minor",
     "description": "Dark electronic, wobble bass, half-time drums"},
    {"name": "Dark Dubstep",     "bpm_min": 138, "bpm_max": 148, "key_mode": "minor",
     "description": "Aggressive Dubstep, minimal harmonic content"},
    {"name": "Techno",           "bpm_min": 128, "bpm_max": 145, "key_mode": "minor",
     "description": "Repetitiv, industrial, vier-auf-dem-Boden"},
    {"name": "House",            "bpm_min": 118, "bpm_max": 132, "key_mode": "minor",
     "description": "Vier-auf-dem-Boden, Bassline, Vocal-Hooks"},
    {"name": "Deep House",       "bpm_min": 118, "bpm_max": 126, "key_mode": "minor",
     "description": "Warm, soulful, jazzy Akkorde"},
    {"name": "Drum and Bass",    "bpm_min": 160, "bpm_max": 180, "key_mode": "minor",
     "description": "Breakbeats, tiefer Bass, hohe BPM"},
    {"name": "Neurofunk",        "bpm_min": 170, "bpm_max": 180, "key_mode": "minor",
     "description": "Komplexe Sounds, wissenschaftliche Ästhetik"},
    {"name": "Trap",             "bpm_min": 130, "bpm_max": 160, "key_mode": "minor",
     "description": "Hi-Hat-Rolls, 808-Bass, harte Snares"},
    {"name": "Hip-Hop",          "bpm_min": 75,  "bpm_max": 100, "key_mode": "minor",
     "description": "Sample-basiert, Boom Bap oder Trap"},
    {"name": "Ambient",          "bpm_min": 60,  "bpm_max": 90,  "key_mode": "minor",
     "description": "Atmosphärisch, langsam, kein klares Tempo"},
    {"name": "Pop",              "bpm_min": 95,  "bpm_max": 128, "key_mode": "major",
     "description": "Eingängige Melodien, klare Struktur"},
    {"name": "Rock",             "bpm_min": 100, "bpm_max": 140, "key_mode": "minor",
     "description": "E-Gitarren-Riffs, Pentatonik, Distortion, aggressive Drums"},
    {"name": "Metal",            "bpm_min": 130, "bpm_max": 200, "key_mode": "minor",
     "description": "Drop-D-Tuning, Palm Mutes, Double Bass, high Gain"},
    {"name": "Blues",            "bpm_min": 70,  "bpm_max": 110, "key_mode": "minor",
     "description": "Blues-Pentatonik, Shuffle, Gitarren-Leads, Bends"},
]

# ── Sound-Typen ───────────────────────────────────────────────────────────────

SOUNDS = [
    {"name": "Reese Bass",     "category": "bass",
     "description": "Detuned sawtooth bass mit Modulation. Klassisch für Dubstep/DnB.",
     "created_by": "FM-4",
     "settings": "Op1+Op2 Ratio 1:1.5, Detune ±8 Cents, Distortion Fold 40%, Ladder-Filter 800Hz"},
    {"name": "Wobble Bass",    "category": "bass",
     "description": "Bass mit rhythmisch moduliertem Filter. Charakteristisch Dubstep.",
     "created_by": "Polysynth",
     "settings": "Saw, LFO → Filter Cutoff, Rate sync 1/4, Depth 0.7"},
    {"name": "808 Bass",       "category": "bass",
     "description": "Langer Sub-Sine Bass. Trap/Hip-Hop.",
     "created_by": "E-Kick",
     "settings": "Tune -12, Decay 2.0s, Sub Level 1.0"},
    {"name": "Techno Kick",    "category": "drums",
     "description": "Harter elektronischer Kick. Pitch-Drop, Sub-Punch.",
     "created_by": "E-Kick",
     "settings": "Tune -18, Punch 0.8, Decay 0.3s, Click 0.5"},
    {"name": "Half-Time Snare","category": "drums",
     "description": "Snare auf Beat 3 (Halftime-Feel). Typisch Dubstep.",
     "created_by": "E-Snare",
     "settings": "Noise 0.7, Decay 0.4s, Reverb 1.5s"},
    {"name": "Dark Pad",       "category": "atmosphere",
     "description": "Dunkles Atmosphären-Pad. Minor Chords, viel Reverb.",
     "created_by": "Polysynth",
     "settings": "Saw+Saw detune, LP-Filter 30%, Reverb 4s, Attack 0.5s"},
    {"name": "Lead Synth",     "category": "lead",
     "description": "Mono-Lead für Melodien und Hooks.",
     "created_by": "Phase-4",
     "settings": "Saw, Phase-Mod 0.3, Filter 60% + Env, LFO Vibrato"},
    {"name": "Vocal Chop",     "category": "fx",
     "description": "Verarbeitete Vocal-Samples als rhythmisches Element.",
     "created_by": "Sampler",
     "settings": "Short samples, Gate, Reverb + Delay"},
    {"name": "Rock Guitar Riff","category": "lead",
     "description": "E-Gitarren-Riff Loop (WAV), Pentatonik, Distortion. Rock/Metal.",
     "created_by": "AudioLoop_GuitarRiff",
     "settings": "find_guitar_loops(key, bpm) → load_guitar_loop(); Distortion+Amp FX hinzufügen"},
    {"name": "Lead Guitar",    "category": "lead",
     "description": "Lead-Gitarren Loop mit Sustain. Rock, Metal.",
     "created_by": "AudioLoop_GuitarLead",
     "settings": "find_guitar_loops(key, bpm, loop_type='GuitarLead') → load_guitar_loop()"},
    {"name": "Heavy Guitar",   "category": "lead",
     "description": "Stark verzerrter Gitarren-Loop. Metal, Heavy Rock.",
     "created_by": "AudioLoop_GuitarRiff",
     "settings": "find_guitar_loops(key, bpm, loop_type='GuitarRiff'); Distortion Drive=0.8+Amp"},
    {"name": "Clean Guitar",   "category": "lead",
     "description": "Sauberer Gitarren-Loop. Pop, Blues, Funk.",
     "created_by": "AudioLoop_GuitarRiff",
     "settings": "find_guitar_loops(key, bpm, loop_type='GuitarChords'); kein Distortion"},
    {"name": "Blues Lead",     "category": "lead",
     "description": "Blues-Gitarren-Lead Loop mit Bend-Charakter. Pentatonik.",
     "created_by": "AudioLoop_GuitarLead",
     "settings": "find_guitar_loops(key, bpm, loop_type='GuitarLead'); leichte Distortion+Amp"},
]

# ── Genre → Device Beziehungen ────────────────────────────────────────────────

GENRE_DEVICES = [
    # Dubstep
    ("Dubstep",      "E-Kick",     "drums",  0.95),
    ("Dubstep",      "E-Snare",    "drums",  0.90),
    ("Dubstep",      "E-HiHat",    "drums",  0.85),
    ("Dubstep",      "FM-4",       "bass",   0.95),
    ("Dubstep",      "Phase-4",    "lead",   0.80),
    ("Dubstep",      "Polysynth",  "pad",    0.75),
    ("Dubstep",      "Distortion", "effect", 0.90),
    ("Dubstep",      "Ladder Filter","effect",0.85),
    ("Dubstep",      "Compressor", "sidechain",0.95),
    # Dark Dubstep
    ("Dark Dubstep", "E-Kick",     "drums",  0.95),
    ("Dark Dubstep", "FM-4",       "bass",   0.98),
    ("Dark Dubstep", "Saturator",  "effect", 0.85),
    ("Dark Dubstep", "Reverb",     "atmosphere",0.80),
    # Techno
    ("Techno",       "E-Kick",     "drums",  0.99),
    ("Techno",       "E-HiHat",    "drums",  0.90),
    ("Techno",       "Polysynth",  "bass",   0.85),
    ("Techno",       "Phase-4",    "lead",   0.80),
    ("Techno",       "Delay-2",    "effect", 0.75),
    # House
    ("House",        "E-Kick",     "drums",  0.95),
    ("House",        "E-Clap",     "drums",  0.90),
    ("House",        "Polysynth",  "bass",   0.90),
    ("House",        "Polysynth",  "chords", 0.85),
    ("House",        "Reverb",     "effect", 0.80),
    # Drum and Bass
    ("Drum and Bass","E-Kick",     "drums",  0.90),
    ("Drum and Bass","E-Snare",    "drums",  0.90),
    ("Drum and Bass","FM-4",       "bass",   0.95),
    ("Drum and Bass","Transient Control","effect",0.80),
    # Rock — echte Gitarren-Loops, keine Synthesizer
    ("Rock",         "AudioLoop_GuitarRiff", "guitar",  0.99),
    ("Rock",         "AudioLoop_GuitarLead", "lead",    0.92),
    ("Rock",         "AudioLoop_BassGuitar", "bass",    0.95),
    ("Rock",         "Distortion",           "effect",  0.98),
    ("Rock",         "Amp",                  "effect",  0.90),
    ("Rock",         "EQ-5",                 "effect",  0.80),
    ("Rock",         "E-Kick",               "drums",   0.90),
    ("Rock",         "E-Snare",              "drums",   0.90),
    # Metal — echte Gitarren-Loops, keine Synthesizer
    ("Metal",        "AudioLoop_GuitarRiff", "guitar",  0.99),
    ("Metal",        "AudioLoop_GuitarLead", "lead",    0.92),
    ("Metal",        "AudioLoop_BassGuitar", "bass",    0.95),
    ("Metal",        "Distortion",           "effect",  0.99),
    ("Metal",        "Amp",                  "effect",  0.95),
    ("Metal",        "E-Kick",               "drums",   0.95),
    # Blues — echte Gitarren-Loops, keine Synthesizer
    ("Blues",        "AudioLoop_GuitarRiff", "guitar",  0.95),
    ("Blues",        "AudioLoop_GuitarLead", "lead",    0.90),
    ("Blues",        "AudioLoop_BassGuitar", "bass",    0.85),
    ("Blues",        "Amp",                  "effect",  0.85),
    ("Blues",        "Reverb",               "effect",  0.80),
]

# ── Empfohlene Effekt-Ketten ──────────────────────────────────────────────────

RECOMMENDED_CHAINS = [
    # Gerät → Empfohlener Effekt + Begründung
    ("E-Kick",    "Compressor",       "Punch kontrollieren, Sidechain-Quelle"),
    ("E-Kick",    "EQ-5",             "Sub-Frequenzen formen, HPF bei 30Hz"),
    ("FM-4",      "Distortion",       "Harmonische Sättigung für Reese-Bass"),
    ("FM-4",      "Ladder Filter",    "Klassischer analoger Klang"),
    ("FM-4",      "Compressor",       "Dynamik glätten"),
    ("Polysynth", "Reverb",           "Räumlichkeit für Pads"),
    ("Polysynth", "Delay-2",          "Stereobreite für Leads"),
    ("E-Snare",   "Reverb",           "Snare-Raumgefühl"),
    ("E-Snare",   "Transient Control","Attack betonen"),
    ("Sampler",   "EQ-5",             "Frequenzkorrektur nach Sample-Typ"),
    ("Phase-4",   "Distortion",       "Gitarren-Distortion/Overdrive"),
    ("Phase-4",   "Amp",              "Amp-Simulation für Gitarren-Sound"),
    ("Phase-4",   "Reverb",           "Raum für Gitarren-Sound"),
]

# ── Workflows / Produktions-Rezepte ──────────────────────────────────────────

WORKFLOWS = [
    {"name": "Dubstep Reese Bass",
     "genre": "Dubstep",
     "description": "Klassischer Reese-Bass für Dubstep",
     "steps": [
         "FM-4 auf Bass-Track laden",
         "Algorithmus: Op1 moduliert Op2 (Kette)",
         "Op1 Ratio: 1.0, Op2 Ratio: 1.5",
         "Op1 Detune: +8 Cents",
         "Distortion hinzufügen: Mode=Fold, Drive=0.4",
         "Ladder-Filter: Cutoff 800Hz, Resonance 0.3",
         "Compressor: Threshold -18dB, Ratio 4:1, Attack 2ms",
     ]},
    {"name": "Dubstep Half-Time Drums",
     "genre": "Dubstep",
     "description": "Half-Time Drum-Pattern für Dark Dubstep",
     "steps": [
         "E-Kick: Tune -18, Punch 0.8, Decay 0.5s",
         "E-Snare auf Beat 3 (half-time), Reverb 1.5s",
         "E-HiHat: 8tel-Noten, alternierende Velocities 60/100",
         "Sidechain: Compressor auf Bass-Track, Input=Kick",
         "Sidechain: Threshold -20dB, Ratio 6:1, Attack 2ms, Release 80ms",
     ]},
    {"name": "Sidechain Kompression",
     "genre": None,
     "description": "Kick → Bass Sidechain Ducking",
     "steps": [
         "Compressor auf Bass-Track",
         "Sidechain Input: Kick-Track auswählen",
         "Threshold: -20 dB",
         "Ratio: 6:1",
         "Attack: 2 ms",
         "Release: 80 ms",
         "Make-Up Gain anpassen bis Lautstärke stimmt",
     ]},
    {"name": "Mastering Chain",
     "genre": None,
     "description": "Standard Mastering-Kette für elektronische Musik",
     "steps": [
         "EQ-5: Korrektur-EQ, HPF bei 30Hz",
         "Compressor: Threshold -18dB, Ratio 2:1, soft knee",
         "Saturator: Drive 0.15 für Wärme",
         "EQ-5: High Shelf +1.5dB bei 8kHz für Luft",
         "Limiter: Ceiling -0.3 dBTP, Lookahead 1ms",
         "Ziel: -14 LUFS für Streaming",
     ]},
]

# ── Graph aufbauen ────────────────────────────────────────────────────────────

def build_graph():
    """Befüllt den Neo4j-Graph mit allen Bitwig-Daten."""
    with session() as s:
        total = 0

        # Genres
        for g in GENRES:
            s.run("""
                MERGE (g:Genre {name: $name})
                SET g.bpm_min=$bpm_min, g.bpm_max=$bpm_max,
                    g.key_mode=$key_mode, g.description=$description
            """, **g)
        print(f"  ✓ {len(GENRES)} Genres")

        # Devices + Parameter
        dev_count, param_count = 0, 0
        for dev in DEVICES:
            params = dev.pop("params", [])
            s.run("""
                MERGE (d:Device {name: $name})
                SET d.type=$type, d.category=$category,
                    d.description=$description, d.browser_path=$browser_path
            """, **dev)
            dev["params"] = params
            dev_count += 1
            for p in params:
                pname = f"{dev['name']}.{p['name']}"
                s.run("""
                    MERGE (p:Parameter {name: $pname})
                    SET p.device=$device, p.param=$param,
                        p.type=$type, p.default=$default,
                        p.unit=$unit, p.values=$values
                    WITH p
                    MATCH (d:Device {name: $device})
                    MERGE (d)-[:HAS_PARAMETER]->(p)
                """,
                    pname=pname,
                    device=dev["name"],
                    param=p["name"],
                    type=p.get("type","float"),
                    default=str(p.get("default","")),
                    unit=p.get("unit",""),
                    values=p.get("values",""),
                )
                param_count += 1
        print(f"  ✓ {dev_count} Devices, {param_count} Parameter")

        # Sounds
        for snd in SOUNDS:
            creator = snd.pop("created_by", None)
            s.run("""
                MERGE (snd:Sound {name: $name})
                SET snd.category=$category, snd.description=$description,
                    snd.settings=$settings
            """, **snd)
            snd["created_by"] = creator
            if creator:
                s.run("""
                    MATCH (snd:Sound {name: $snd}), (d:Device {name: $dev})
                    MERGE (snd)-[:CREATED_BY]->(d)
                """, snd=snd["name"], dev=creator)
        print(f"  ✓ {len(SOUNDS)} Sounds")

        # Genre → Device — zuerst veraltete guitar/lead-Synth-Beziehungen für Loop-Genres löschen
        s.run("""
            MATCH (g:Genre)-[r:USES]->(d:Device {name: "Phase-4"})
            WHERE g.name IN ["Rock", "Metal", "Blues"]
              AND r.role IN ["guitar", "lead"]
            DELETE r
        """)
        for genre, device, role, weight in GENRE_DEVICES:
            s.run("""
                MATCH (g:Genre {name: $genre}), (d:Device {name: $device})
                MERGE (g)-[r:USES {role: $role}]->(d)
                SET r.weight = $weight
            """, genre=genre, device=device, role=role, weight=weight)
        print(f"  ✓ {len(GENRE_DEVICES)} Genre→Device Beziehungen")

        # Empfohlene Ketten
        for device, effect, reason in RECOMMENDED_CHAINS:
            s.run("""
                MATCH (d:Device {name: $device}), (e:Device {name: $effect})
                MERGE (d)-[r:RECOMMENDED_WITH]->(e)
                SET r.reason = $reason
            """, device=device, effect=effect, reason=reason)
        print(f"  ✓ {len(RECOMMENDED_CHAINS)} Empfohlene Ketten")

        # Workflows
        for wf in WORKFLOWS:
            genre = wf.get("genre")
            s.run("""
                MERGE (w:Workflow {name: $name})
                SET w.description=$description, w.steps=$steps
            """, name=wf["name"], description=wf["description"],
                 steps="\n".join(wf["steps"]))
            if genre:
                s.run("""
                    MATCH (w:Workflow {name: $wf}), (g:Genre {name: $genre})
                    MERGE (w)-[:USED_IN]->(g)
                """, wf=wf["name"], genre=genre)
        print(f"  ✓ {len(WORKFLOWS)} Workflows")

    print("✓ Graph aufgebaut")

# ── Query-Interface ───────────────────────────────────────────────────────────

def query_for_genre(genre_name: str) -> dict:
    """Alle Devices, Sounds und Workflows für ein Genre."""
    with session() as s:
        devices = s.run("""
            MATCH (g:Genre)-[r:USES]->(d:Device)
            WHERE g.name =~ $pattern
            RETURN d.name AS device, d.category AS category,
                   r.role AS role, r.weight AS weight, d.description AS desc
            ORDER BY r.weight DESC
        """, pattern=f"(?i).*{genre_name}.*").data()

        workflows = s.run("""
            MATCH (w:Workflow)-[:USED_IN]->(g:Genre)
            WHERE g.name =~ $pattern
            RETURN w.name AS name, w.description AS desc, w.steps AS steps
        """, pattern=f"(?i).*{genre_name}.*").data()

        sounds = s.run("""
            MATCH (g:Genre)-[:TYPICAL_SOUND]->(snd:Sound)
            WHERE g.name =~ $pattern
            RETURN snd.name AS sound, snd.settings AS settings
        """, pattern=f"(?i).*{genre_name}.*").data()

    return {"devices": devices, "workflows": workflows, "sounds": sounds}


def query_device_setup(device_name: str) -> dict:
    """Parameter + empfohlene Effektkette für ein Device."""
    with session() as s:
        params = s.run("""
            MATCH (d:Device {name: $name})-[:HAS_PARAMETER]->(p:Parameter)
            RETURN p.param AS param, p.type AS type,
                   p.default AS default, p.unit AS unit, p.values AS values
            ORDER BY p.param
        """, name=device_name).data()

        chain = s.run("""
            MATCH (d:Device {name: $name})-[r:RECOMMENDED_WITH]->(fx:Device)
            RETURN fx.name AS effect, r.reason AS reason
        """, name=device_name).data()

        info = s.run("""
            MATCH (d:Device {name: $name})
            RETURN d.description AS desc, d.browser_path AS path,
                   d.category AS category
        """, name=device_name).single()

    return {
        "device": device_name,
        "info": dict(info) if info else {},
        "parameters": params,
        "recommended_chain": chain,
    }


def store_song_analysis_neo4j(
    filename: str, bpm: float, key: str,
    genre: str, subgenre: str, confidence: float,
    present_stems: list[str], stem_analyses: dict,
) -> str:
    """Speichert Song-Analyse im Graph."""
    with session() as s:
        s.run("""
            MERGE (song:Song {filename: $filename})
            SET song.bpm=$bpm, song.key=$key, song.confidence=$confidence
            WITH song
            MATCH (g:Genre)
            WHERE g.name =~ $genre_pat
            MERGE (song)-[:CLASSIFIED_AS {confidence: $confidence}]->(g)
        """, filename=filename, bpm=bpm, key=key, confidence=confidence,
             genre_pat=f"(?i).*{subgenre or genre}.*")

        for stem_name, analysis in stem_analyses.items():
            s.run("""
                MERGE (stem:Stem {id: $stem_id})
                SET stem.name=$name, stem.song=$song,
                    stem.has_content=$has_content, stem.character=$character,
                    stem.confidence=$confidence
                WITH stem
                MATCH (song:Song {filename: $song})
                MERGE (song)-[:HAS_STEM]->(stem)
            """,
                stem_id=f"{filename}:{stem_name}",
                name=stem_name, song=filename,
                has_content=analysis.get("has_content", False),
                character=analysis.get("character", ""),
                confidence=analysis.get("confidence", 0.0),
            )
    return filename
