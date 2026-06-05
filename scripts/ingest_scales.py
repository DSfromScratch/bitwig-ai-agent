"""
Ingest: Alle 24 Tonarten (12 Dur + 12 Moll) + häufige Akkorde in Neo4j.
Verknüpft vorhandene MidiClip-Nodes mit ihrer Tonart via IN_KEY Relation.

Run: python scripts/ingest_scales.py
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

# ── Intervalle ────────────────────────────────────────────────────────────────
MAJOR_INT = [0, 2, 4, 5, 7, 9, 11]
MINOR_INT = [0, 2, 3, 5, 7, 8, 10]   # natural minor

# Chromatische Namen (Index = Halbton ab C)
CHROMA_DE = ["C", "Cis", "D", "Es", "E", "F", "Fis", "G", "As", "A", "B", "H"]
CHROMA_EN = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# 12 Grundtöne: (deutsch, englisch, MIDI-C4-Basis)
ROOTS = [
    ("C",   "C",  60),
    ("Cis", "C#", 61),
    ("D",   "D",  62),
    ("Es",  "Eb", 63),
    ("E",   "E",  64),
    ("F",   "F",  65),
    ("Fis", "F#", 66),
    ("G",   "G",  67),
    ("As",  "Ab", 68),
    ("A",   "A",  69),
    ("B",   "Bb", 70),
    ("H",   "B",  71),
]


def _note_names(notes: list[int], lang: str = "de") -> list[str]:
    table = CHROMA_DE if lang == "de" else CHROMA_EN
    return [table[n % 12] for n in notes]


def _build_scales() -> list[dict]:
    scales = []
    for de, en, midi in ROOTS:
        root_idx = midi % 12
        rel_minor_idx = (root_idx + 9) % 12   # Paralleltonart Moll
        rel_major_idx = (root_idx + 3) % 12   # Paralleltonart Dur

        for mode, intervals, suffix_de, suffix_en, rel_de, rel_en in [
            ("major", MAJOR_INT, "Dur",  "major",
             f"{CHROMA_DE[rel_minor_idx]}-Moll", f"{CHROMA_EN[rel_minor_idx]} minor"),
            ("minor", MINOR_INT, "Moll", "minor",
             f"{CHROMA_DE[rel_major_idx]}-Dur",  f"{CHROMA_EN[rel_major_idx]} major"),
        ]:
            notes = [midi + i for i in intervals]
            scales.append({
                "name_de":       f"{de}-{suffix_de}",
                "name_en":       f"{en} {suffix_en}",
                "root_de":       de,
                "root_en":       en,
                "type":          mode,
                "midi_root":     midi,
                "notes":         notes,
                "note_names_de": _note_names(notes, "de"),
                "note_names_en": _note_names(notes, "en"),
                "relative_de":   rel_de,
                "relative_en":   rel_en,
            })
    return scales


# Akkord-Qualitäten: (quality_id, intervalle, symbol-Template, name_de-Template)
CHORD_QUALITIES = [
    ("major",  [0, 4, 7],      "{r}",     "{d}-Dur"),
    ("minor",  [0, 3, 7],      "{r}m",    "{d}-Moll"),
    ("dom7",   [0, 4, 7, 10],  "{r}7",    "{d}-Dom7"),
    ("maj7",   [0, 4, 7, 11],  "{r}maj7", "{d}-Dur7"),
    ("min7",   [0, 3, 7, 10],  "{r}m7",   "{d}-Moll7"),
    ("dim",    [0, 3, 6],      "{r}dim",  "{d}-Dim"),
    ("sus4",   [0, 5, 7],      "{r}sus4", "{d}-Sus4"),
]

# Diatonische Akkord-Qualitäten pro Skalenstufe
MAJOR_DIATONIC = ["major", "minor", "minor", "major", "major", "minor", "dim"]
MINOR_DIATONIC = ["minor", "dim",   "major", "minor", "minor", "major", "major"]


def _build_chords() -> list[dict]:
    chords = []
    for de, en, midi in ROOTS:
        for quality, intervals, sym_tmpl, name_tmpl in CHORD_QUALITIES:
            notes = [midi + i for i in intervals]
            chords.append({
                "symbol":        sym_tmpl.replace("{r}", en),
                "name_de":       name_tmpl.replace("{d}", de),
                "root_de":       de,
                "root_en":       en,
                "quality":       quality,
                "midi_root":     midi,
                "notes":         notes,
                "note_names_de": _note_names(notes, "de"),
                "note_names_en": _note_names(notes, "en"),
            })
    return chords


def main() -> None:
    from neo4j import GraphDatabase

    uri  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER",     "neo4j")
    pwd  = os.getenv("NEO4J_PASSWORD", "neo4jllm")

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    scales = _build_scales()
    chords = _build_chords()

    with driver.session() as s:
        # Constraints
        s.run("CREATE CONSTRAINT scale_name_de IF NOT EXISTS "
              "FOR (n:Scale) REQUIRE n.name_de IS UNIQUE")
        s.run("CREATE CONSTRAINT chord_symbol IF NOT EXISTS "
              "FOR (n:Chord) REQUIRE n.symbol IS UNIQUE")

        # ── Scales ────────────────────────────────────────────────────────────
        print(f"Ingesting {len(scales)} scales…")
        for sc in scales:
            s.run("""
                MERGE (n:Scale {name_de: $name_de})
                SET n.name_en       = $name_en,
                    n.root_de       = $root_de,
                    n.root_en       = $root_en,
                    n.type          = $type,
                    n.midi_root     = $midi_root,
                    n.notes         = $notes,
                    n.note_names_de = $note_names_de,
                    n.note_names_en = $note_names_en,
                    n.relative_de   = $relative_de,
                    n.relative_en   = $relative_en
            """, **sc)

        # RELATIVE_OF
        for sc in scales:
            s.run("""
                MATCH (a:Scale {name_de: $a}), (b:Scale {name_de: $b})
                MERGE (a)-[:RELATIVE_OF]->(b)
            """, a=sc["name_de"], b=sc["relative_de"])

        # ── Chords ────────────────────────────────────────────────────────────
        print(f"Ingesting {len(chords)} chords…")
        for ch in chords:
            s.run("""
                MERGE (n:Chord {symbol: $symbol})
                SET n.name_de       = $name_de,
                    n.root_de       = $root_de,
                    n.root_en       = $root_en,
                    n.quality       = $quality,
                    n.midi_root     = $midi_root,
                    n.notes         = $notes,
                    n.note_names_de = $note_names_de,
                    n.note_names_en = $note_names_en
            """, **ch)

        # ── DIATONIC_CHORD Relations ──────────────────────────────────────────
        print("Creating DIATONIC_CHORD relations…")
        for sc in scales:
            intervals = MAJOR_INT if sc["type"] == "major" else MINOR_INT
            diatonic  = MAJOR_DIATONIC if sc["type"] == "major" else MINOR_DIATONIC
            for degree, (interval, quality) in enumerate(zip(intervals, diatonic), 1):
                chord_root_en = CHROMA_EN[(sc["midi_root"] + interval) % 12]
                suffix = "" if quality == "major" else "m" if quality == "minor" else "dim"
                chord_symbol = f"{chord_root_en}{suffix}"
                s.run("""
                    MATCH (sc:Scale {name_de: $scale}), (ch:Chord {symbol: $chord})
                    MERGE (sc)-[:DIATONIC_CHORD {degree: $deg}]->(ch)
                """, scale=sc["name_de"], chord=chord_symbol, deg=degree)

        # ── Link MidiClips → Scale via full_key ───────────────────────────────
        print("Linking MidiClips to Scales…")
        result = s.run("""
            MATCH (mc:MidiClip)
            WHERE mc.full_key IS NOT NULL
            MATCH (sc:Scale)
            WHERE sc.name_en = mc.full_key
               OR toLower(sc.name_en) = toLower(mc.full_key)
               OR sc.name_de = mc.full_key
            MERGE (mc)-[:IN_KEY]->(sc)
            RETURN count(*) AS n
        """).single()
        linked = result["n"] if result else 0

        # Summary
        scale_count = s.run("MATCH (n:Scale) RETURN count(n) AS n").single()["n"]
        chord_count = s.run("MATCH (n:Chord) RETURN count(n) AS n").single()["n"]
        rel_count   = s.run("MATCH ()-[r:IN_KEY]->() RETURN count(r) AS n").single()["n"]

    driver.close()
    print(f"\n✅ {scale_count} Scales | {chord_count} Chords | {rel_count} IN_KEY Relationen")


if __name__ == "__main__":
    main()
