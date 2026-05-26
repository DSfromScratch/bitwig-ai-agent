"""
Fügt semantische Relationships zwischen bestehenden Neo4j-Nodes hinzu:

  - Device -[:SIMILAR_TO]-> Device      (gleiche Kategorie/Funktion)
  - Device -[:USED_IN]-> Workflow       (Device-Name in Workflow-Schritten erwähnt)
  - Concept -[:RELATED_TO]-> Device     (Konzept-Name in Device-Beschreibung erwähnt)
  - Genre   -[:USES]-> Device           (erweiterte Genre-Device-Sets)

Usage:
    source .venv/bin/activate
    python scripts/ingest_cross_links.py [--dry-run]
"""
from __future__ import annotations
import argparse, os, sys, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from neo4j import GraphDatabase

NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jllm")


# ── 1. SIMILAR_TO: Device-Ähnlichkeitsgruppen ─────────────────────────────────
# Jede Gruppe = Devices die ähnlich klingen / fungieren → alle untereinander verlinkt

SIMILARITY_GROUPS = [
    # Filter
    {"reason": "resonant filter", "devices": [
        "SVF", "Low-pass LD", "Low-pass MG", "Sallen-Key", "XP", "Ladder Filter",
        "Filter +",
    ]},
    {"reason": "character filter", "devices": [
        "Vowels", "Comb", "Fizz", "Rasp", "Ripple",
    ]},
    # Kompressor-Familie
    {"reason": "dynamic compression", "devices": [
        "Compressor", "Multiband Compressor", "Transient Control",
        "Compressor+", "Limiter",
    ]},
    # EQ-Familie
    {"reason": "equalization", "devices": [
        "EQ-2", "EQ-5", "EQ+", "EQ-DJ",
    ]},
    # Delay-Familie
    {"reason": "delay effect", "devices": [
        "Delay-1", "Delay+", "Dual Delay", "Delay", "Long Delay", "Mod Delay",
    ]},
    # Chorus/Modulation
    {"reason": "modulation effect", "devices": [
        "Chorus+", "Flanger+", "Phaser+", "Freq Shift+",
    ]},
    # Reverb
    {"reason": "reverb / spatial", "devices": [
        "Reverb", "Convolution Reverb", "Convolution Reverb Pro",
    ]},
    # Waveshaper/Distortion
    {"reason": "distortion / saturation", "devices": [
        "Saturator", "Amp", "Cabinet", "Overdrive", "Wavefolder",
        "Push", "Heat", "Howl", "Shred", "Chebyshev", "Diode",
    ]},
    # Synthesizer (analog-style)
    {"reason": "subtractive synthesizer", "devices": [
        "Phase-4", "Polysynth", "Polymer",
    ]},
    # FM Synthesis
    {"reason": "FM synthesizer", "devices": [
        "FM-4", "Phase-1", "Bite",
    ]},
    # Sample-Player
    {"reason": "sample playback", "devices": [
        "Sampler", "Drum Machine",
    ]},
    # Percussion
    {"reason": "electronic drum synthesis", "devices": [
        "E-Kick", "E-Snare", "E-Hat", "E-Clap", "E-Tom", "E-Cowbell",
    ]},
    # LFO-Familie
    {"reason": "LFO modulator", "devices": [
        "LFO", "Curves", "S/H LFO", "Beat LFO", "Classic LFO",
    ]},
    # Envelope
    {"reason": "envelope generator", "devices": [
        "ADSR", "AD", "AR", "Segments", "Pluck", "AHD on Release", "AHDSR",
    ]},
    # Oscillatoren
    {"reason": "oscillator", "devices": [
        "Wavetable", "Swarm", "Union", "Sawtooth", "Pulse",
        "Sine", "Triangle", "Scrawl", "Phase-1",
    ]},
    # Utility Gain/Level
    {"reason": "gain / level control", "devices": [
        "Tool", "Gain - dB", "Gain - Vol", "LR Gain", "Amplify", "Attenuate",
    ]},
    # Spektral-Analyse
    {"reason": "spectrum analysis", "devices": [
        "Spectrum", "Oscilloscope", "VU Meter",
    ]},
    # Pitch
    {"reason": "pitch processing", "devices": [
        "Transpose", "Octaver", "Pitch Quantize", "Ratio", "Pitch Shift",
    ]},
]


# ── 2. Genre-Device-Sets (vollständig) ───────────────────────────────────────

GENRE_DEVICES: dict[str, list[dict]] = {
    "Techno": [
        {"device": "Phase-4",          "role": "kick synth / bass",     "weight": 10},
        {"device": "Drum Machine",     "role": "drum sequencer",        "weight": 10},
        {"device": "Delay+",           "role": "rhythmic delay",        "weight": 8},
        {"device": "Reverb",           "role": "space / atmosphere",    "weight": 8},
        {"device": "Compressor",       "role": "sidechain compression", "weight": 9},
        {"device": "EQ-5",             "role": "frequency shaping",     "weight": 7},
        {"device": "Ladder Filter",    "role": "acid bass filter",      "weight": 9},
        {"device": "FM-4",             "role": "metallic stabs",        "weight": 6},
        {"device": "Saturator",        "role": "analog warmth",         "weight": 6},
        {"device": "Polysynth",        "role": "pad / atmosphere",      "weight": 5},
    ],
    "House": [
        {"device": "Drum Machine",     "role": "four-on-the-floor",     "weight": 10},
        {"device": "Phase-4",          "role": "bass synth",            "weight": 9},
        {"device": "Compressor",       "role": "sidechain ducking",     "weight": 10},
        {"device": "Reverb",           "role": "space",                 "weight": 8},
        {"device": "Chorus+",          "role": "pad width",             "weight": 6},
        {"device": "EQ-5",             "role": "mix balance",           "weight": 7},
        {"device": "Polysynth",        "role": "chords / pads",         "weight": 8},
        {"device": "Delay+",           "role": "vocal delay",           "weight": 6},
        {"device": "Ladder Filter",    "role": "filter sweeps",         "weight": 7},
        {"device": "Sampler",          "role": "vocal chops",           "weight": 6},
    ],
    "Deep House": [
        {"device": "Polysynth",        "role": "deep chords / bass",    "weight": 10},
        {"device": "Compressor",       "role": "sidechain compression", "weight": 9},
        {"device": "Reverb",           "role": "lush atmosphere",       "weight": 10},
        {"device": "Delay+",           "role": "melodic delay",         "weight": 8},
        {"device": "EQ-5",             "role": "frequency shaping",     "weight": 7},
        {"device": "Drum Machine",     "role": "subtle groove",         "weight": 8},
        {"device": "Chorus+",          "role": "warmth and width",      "weight": 7},
        {"device": "Phase-4",          "role": "sub bass",              "weight": 8},
        {"device": "Sampler",          "role": "vinyl loops",           "weight": 6},
    ],
    "Drum and Bass": [
        {"device": "Drum Machine",     "role": "amen break / resampling","weight": 10},
        {"device": "Compressor",       "role": "parallel compression",  "weight": 9},
        {"device": "Transient Control","role": "drum shaping",          "weight": 8},
        {"device": "Ladder Filter",    "role": "reese bass filter",     "weight": 10},
        {"device": "FM-4",             "role": "reese bass source",     "weight": 9},
        {"device": "Reverb",           "role": "atmosphere",            "weight": 6},
        {"device": "Delay+",           "role": "rhythmic texture",      "weight": 6},
        {"device": "EQ-5",             "role": "frequency separation",  "weight": 8},
        {"device": "Saturator",        "role": "grit and dirt",         "weight": 7},
        {"device": "Phase-4",          "role": "pads / stabs",          "weight": 5},
    ],
    "Dubstep": [
        {"device": "FM-4",             "role": "wobble bass / growl",   "weight": 10},
        {"device": "Ladder Filter",    "role": "wub filter sweep",      "weight": 10},
        {"device": "Compressor",       "role": "sidechain",             "weight": 9},
        {"device": "Drum Machine",     "role": "half-time drums",       "weight": 10},
        {"device": "Transient Control","role": "drum punch",            "weight": 7},
        {"device": "Saturator",        "role": "bass distortion",       "weight": 8},
        {"device": "Reverb",           "role": "space / tension",       "weight": 6},
        {"device": "Delay+",           "role": "effect delay",          "weight": 5},
        {"device": "Phase-4",          "role": "synth stabs",           "weight": 6},
        {"device": "EQ-5",             "role": "low-end sculpting",     "weight": 7},
    ],
    "Dark Dubstep": [
        {"device": "FM-4",             "role": "dark growl / bass",     "weight": 10},
        {"device": "Ladder Filter",    "role": "dark filter",           "weight": 10},
        {"device": "Saturator",        "role": "heavy distortion",      "weight": 9},
        {"device": "Compressor",       "role": "sidechain / punch",     "weight": 9},
        {"device": "Reverb",           "role": "dark atmosphere",       "weight": 8},
        {"device": "Drum Machine",     "role": "half-time pattern",     "weight": 10},
        {"device": "Delay+",           "role": "cinematic delay",       "weight": 7},
        {"device": "EQ-5",             "role": "low-end control",       "weight": 7},
    ],
    "Neurofunk": [
        {"device": "FM-4",             "role": "neuro bass source",     "weight": 10},
        {"device": "Ladder Filter",    "role": "formant-style filter",  "weight": 10},
        {"device": "Saturator",        "role": "extreme distortion",    "weight": 9},
        {"device": "Compressor",       "role": "parallel compression",  "weight": 8},
        {"device": "Drum Machine",     "role": "complex breakbeat",     "weight": 10},
        {"device": "EQ-5",             "role": "surgical EQ",           "weight": 8},
        {"device": "Reverb",           "role": "sterile space",         "weight": 5},
        {"device": "Transient Control","role": "drum precision",        "weight": 7},
    ],
    "Hip-Hop": [
        {"device": "Sampler",          "role": "sample chops / loops",  "weight": 10},
        {"device": "Drum Machine",     "role": "boom-bap / trap drums", "weight": 10},
        {"device": "Compressor",       "role": "glue compression",      "weight": 9},
        {"device": "EQ-5",             "role": "low-end warmth",        "weight": 8},
        {"device": "Reverb",           "role": "vintage space",         "weight": 7},
        {"device": "Delay+",           "role": "vocal doubling",        "weight": 6},
        {"device": "Saturator",        "role": "vinyl warmth",          "weight": 6},
        {"device": "Polysynth",        "role": "keys / chords",         "weight": 5},
    ],
    "Trap": [
        {"device": "Drum Machine",     "role": "hi-hat rolls / 808",    "weight": 10},
        {"device": "Sampler",          "role": "808 bass / samples",    "weight": 10},
        {"device": "Compressor",       "role": "loud / punchy mix",     "weight": 9},
        {"device": "Reverb",           "role": "snare reverb",          "weight": 8},
        {"device": "EQ-5",             "role": "sub bass clarity",      "weight": 8},
        {"device": "Delay+",           "role": "hi-hat delay",          "weight": 6},
        {"device": "Saturator",        "role": "808 saturation",        "weight": 7},
        {"device": "Phase-4",          "role": "synth leads",           "weight": 5},
    ],
    "Ambient": [
        {"device": "Reverb",           "role": "massive reverb tails",  "weight": 10},
        {"device": "Convolution Reverb","role": "space design",         "weight": 9},
        {"device": "Delay+",           "role": "infinite repeats",      "weight": 10},
        {"device": "Polysynth",        "role": "sustained pads",        "weight": 10},
        {"device": "Phase-4",          "role": "evolving textures",     "weight": 8},
        {"device": "Chorus+",          "role": "shimmer / width",       "weight": 8},
        {"device": "EQ-5",             "role": "tonal sculpting",       "weight": 6},
        {"device": "Compressor",       "role": "gentle dynamics",       "weight": 5},
        {"device": "Sampler",          "role": "field recordings",      "weight": 7},
        {"device": "FM-4",             "role": "evolving FM textures",  "weight": 6},
    ],
    "Pop": [
        {"device": "Compressor",       "role": "vocal / bus compression","weight": 10},
        {"device": "EQ-5",             "role": "mix clarity",           "weight": 10},
        {"device": "Reverb",           "role": "vocal space",           "weight": 9},
        {"device": "Delay+",           "role": "vocal delay",           "weight": 8},
        {"device": "Chorus+",          "role": "synth width",           "weight": 7},
        {"device": "Drum Machine",     "role": "programmed drums",      "weight": 8},
        {"device": "Polysynth",        "role": "synth pad / keys",      "weight": 8},
        {"device": "Sampler",          "role": "loops and stabs",       "weight": 6},
        {"device": "Limiter",          "role": "master bus limiting",   "weight": 8},
        {"device": "Saturator",        "role": "presence and warmth",   "weight": 6},
    ],
    "Rock": [
        {"device": "Amp",              "role": "guitar amplifier",      "weight": 10},
        {"device": "Cabinet",          "role": "speaker simulation",    "weight": 10},
        {"device": "Overdrive",        "role": "guitar distortion",     "weight": 9},
        {"device": "Compressor",       "role": "drum / bus compression","weight": 8},
        {"device": "EQ-5",             "role": "frequency balance",     "weight": 7},
        {"device": "Reverb",           "role": "room sound",            "weight": 7},
        {"device": "Delay+",           "role": "guitar delay",          "weight": 6},
        {"device": "Drum Machine",     "role": "programmed drums",      "weight": 6},
        {"device": "Transient Control","role": "drum punch",            "weight": 7},
    ],
    "Metal": [
        {"device": "Amp",              "role": "high-gain guitar",      "weight": 10},
        {"device": "Cabinet",          "role": "tight cab simulation",  "weight": 10},
        {"device": "Overdrive",        "role": "boost before amp",      "weight": 8},
        {"device": "Compressor",       "role": "drum bus compression",  "weight": 9},
        {"device": "EQ-5",             "role": "surgical mid scoop",    "weight": 9},
        {"device": "Transient Control","role": "tight drum attack",     "weight": 8},
        {"device": "Reverb",           "role": "large room drums",      "weight": 6},
        {"device": "Drum Machine",     "role": "programmed drums",      "weight": 7},
        {"device": "Saturator",        "role": "bass saturation",       "weight": 6},
    ],
    "Blues": [
        {"device": "Amp",              "role": "warm tube amplifier",   "weight": 10},
        {"device": "Cabinet",          "role": "vintage speaker",       "weight": 9},
        {"device": "Saturator",        "role": "tube warmth",           "weight": 8},
        {"device": "Reverb",           "role": "spring reverb",         "weight": 9},
        {"device": "Delay+",           "role": "slapback delay",        "weight": 8},
        {"device": "EQ-5",             "role": "midrange presence",     "weight": 7},
        {"device": "Compressor",       "role": "gentle dynamics",       "weight": 6},
    ],
}


# ── 3. Concept → Device Links ─────────────────────────────────────────────────

CONCEPT_DEVICE_LINKS = [
    # Sidechain
    ("Sidechain",              "Compressor",          "ENABLES"),
    ("Sidechain Kompression",  "Compressor",          "ENABLES"),
    ("Sidechain",              "Compressor+",         "ENABLES"),
    # EQ / Frequency
    ("EQ",                     "EQ-5",                "RELATED_TO"),
    ("EQ",                     "EQ-2",                "RELATED_TO"),
    ("EQ",                     "EQ+",                 "RELATED_TO"),
    # Modulation
    ("Modulation",             "LFO",                 "RELATED_TO"),
    ("Modulation",             "ADSR",                "RELATED_TO"),
    ("Modulation",             "Macro",               "RELATED_TO"),
    # Grid
    ("The Grid",               "Poly Grid",           "ENABLES"),
    ("The Grid",               "FX Grid",             "ENABLES"),
    ("The Grid",               "Note Grid",           "ENABLES"),
    # Synthesis
    ("FM Synthesis",           "FM-4",                "EXPLAINS"),
    ("Subtractive Synthesis",  "Phase-4",             "EXPLAINS"),
    ("Subtractive Synthesis",  "Polysynth",           "EXPLAINS"),
    ("Wavetable Synthesis",    "Wavetable",           "EXPLAINS"),
    ("Granular Synthesis",     "Sampler",             "EXPLAINS"),
    # Mastering
    ("Mastering",              "EQ-5",                "USED_IN"),
    ("Mastering",              "Compressor",          "USED_IN"),
    ("Mastering",              "Limiter",             "USED_IN"),
    # Drum shaping
    ("Transient",              "Transient Control",   "RELATED_TO"),
    ("Groove",                 "Drum Machine",        "RELATED_TO"),
]


# ── 4. Workflow → Device REQUIRES ────────────────────────────────────────────

def build_workflow_device_links(session) -> list[tuple[str, str]]:
    """Extrahiert Device-Namen aus Workflow-Beschreibungen und Steps."""
    all_devices = session.run("MATCH (d:Device) RETURN d.name AS n").data()
    device_names = [d["n"] for d in all_devices]

    workflows = session.run("""
        MATCH (w:Workflow)
        RETURN w.name AS name,
               coalesce(w.description, '') + ' ' + coalesce(w.use_case, '') + ' ' + coalesce(w.steps, '') AS text
    """).data()

    links: list[tuple[str, str]] = []
    for wf in workflows:
        text_lower = wf["text"].lower()
        for dev in device_names:
            if len(dev) < 3:
                continue
            if dev.lower() in text_lower:
                links.append((wf["name"], dev))
    return links


# ── Main ──────────────────────────────────────────────────────────────────────

def run(driver, dry_run: bool):
    counts = {
        "similar_to": 0,
        "genre_uses": 0,
        "concept_device": 0,
        "workflow_requires": 0,
    }

    with driver.session() as s:

        # ── 1. SIMILAR_TO ──────────────────────────────────────────────────
        print("[1/4] Erstelle SIMILAR_TO-Beziehungen …")
        for group in SIMILARITY_GROUPS:
            existing = s.run(
                "MATCH (d:Device) WHERE d.name IN $names RETURN d.name AS n",
                names=group["devices"]
            ).data()
            found = [r["n"] for r in existing]
            for i, a in enumerate(found):
                for b in found[i+1:]:
                    if not dry_run:
                        s.run("""
                            MATCH (a:Device {name: $a}), (b:Device {name: $b})
                            MERGE (a)-[:SIMILAR_TO {reason: $reason}]->(b)
                            MERGE (b)-[:SIMILAR_TO {reason: $reason}]->(a)
                        """, a=a, b=b, reason=group["reason"])
                    counts["similar_to"] += 1

        print(f"  → {counts['similar_to']} SIMILAR_TO Paare")

        # ── 2. Genre USES ──────────────────────────────────────────────────
        print("[2/4] Erstelle Genre-USES-Beziehungen …")
        for genre_name, devices in GENRE_DEVICES.items():
            for entry in devices:
                exists = s.run(
                    "MATCH (d:Device {name: $n}) RETURN d.name",
                    n=entry["device"]
                ).single()
                if not exists:
                    continue
                if not dry_run:
                    s.run("""
                        MATCH (g:Genre {name: $genre}), (d:Device {name: $device})
                        MERGE (g)-[r:USES {role: $role, weight: $weight}]->(d)
                    """, genre=genre_name, device=entry["device"],
                         role=entry["role"], weight=entry["weight"])
                counts["genre_uses"] += 1

        print(f"  → {counts['genre_uses']} Genre-USES Links")

        # ── 3. Concept RELATED_TO / ENABLES / EXPLAINS Device ─────────────
        print("[3/4] Erstelle Concept→Device-Beziehungen …")
        for concept_name, device_name, rel_type in CONCEPT_DEVICE_LINKS:
            c_exists = s.run(
                "MATCH (c:Concept) WHERE toLower(c.name) CONTAINS toLower($n) RETURN c.name LIMIT 1",
                n=concept_name
            ).single()
            d_exists = s.run(
                "MATCH (d:Device {name: $n}) RETURN d.name", n=device_name
            ).single()
            if not c_exists or not d_exists:
                continue
            if not dry_run:
                s.run(f"""
                    MATCH (c:Concept) WHERE toLower(c.name) CONTAINS toLower($cn)
                    MATCH (d:Device {{name: $dn}})
                    WITH c, d LIMIT 1
                    MERGE (c)-[:{rel_type}]->(d)
                """, cn=concept_name, dn=device_name)
            counts["concept_device"] += 1

        print(f"  → {counts['concept_device']} Concept→Device Links")

        # ── 4. Workflow REQUIRES Device (automatisch aus Text) ─────────────
        print("[4/4] Erstelle Workflow-REQUIRES-Device-Beziehungen …")
        links = build_workflow_device_links(s)
        for wf_name, dev_name in links:
            if not dry_run:
                s.run("""
                    MATCH (w:Workflow {name: $wf}), (d:Device {name: $dev})
                    MERGE (w)-[:REQUIRES]->(d)
                """, wf=wf_name, dev=dev_name)
            counts["workflow_requires"] += 1

        print(f"  → {counts['workflow_requires']} Workflow→Device Links")

    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    if args.dry_run:
        print("[dry-run] Keine Schreiboperationen\n")

    counts = run(driver, args.dry_run)
    driver.close()

    print(f"\n[done] similar_to={counts['similar_to']}, genre_uses={counts['genre_uses']}, "
          f"concept_device={counts['concept_device']}, workflow_requires={counts['workflow_requires']}")


if __name__ == "__main__":
    main()
