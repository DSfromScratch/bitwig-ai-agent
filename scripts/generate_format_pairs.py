"""
Ebene 2 Trainingsdaten: Theorie → MIDI-Schritte → write_pattern()-Tool-Aufrufe.

Output: data/training/format_pairs.jsonl
Format: {"prompt": "...", "completion": "...", "source": "format"}

Generiert Chord→MIDI, Progression→write_pattern, Melodie→write_pattern.
"""
from __future__ import annotations
import os, sys, json, random
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.knowledge.neo4j_graph import session

OUTPUT = Path("data/training/format_pairs.jsonl")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

MIDI_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_name(midi: int) -> str:
    octave = (midi // 12) - 1
    name   = MIDI_NAMES[midi % 12]
    return f"{name}{octave}"


def transpose_to_octave(base_notes: list[int], target_octave: int = 4) -> list[int]:
    """Transponiert Basis-Noten (C4=60 Basis) zu target_octave."""
    root_base = base_notes[0]
    root_octave_offset = (target_octave * 12 + 12) - (root_base // 12 * 12 + 12)
    return [n + root_octave_offset for n in base_notes]


def chord_to_notes_json(notes: list[int], step: int = 0, duration: int = 16,
                         velocity: float = 0.8) -> list[dict]:
    return [{"pitch": n, "step": step, "duration": duration,
             "velocity": velocity, "channel": 0}
            for n in notes]


def format_notes_compact(notes_json: list[dict]) -> str:
    """Format wie write_pattern erwartet: [C4(s0,d16), E4(s0,d16), G4(s0,d16)]"""
    parts = [f"{midi_name(n['pitch'])}(s{n['step']},d{n['duration']})" for n in notes_json]
    return "[" + ", ".join(parts) + "]"


def load_chords_per_scale(s) -> dict[str, list[dict]]:
    rows = s.run("""
        MATCH (sc:Scale)-[r:DIATONIC_CHORD]->(c:Chord)
        RETURN sc.name_de AS scale, sc.name_en AS scale_en,
               r.degree AS degree, r.degree_name AS dn,
               c.name_de AS chord_de, c.notes AS base_notes, c.quality AS quality
        ORDER BY sc.name_de, r.degree
    """).data()
    result: dict[str, list] = {}
    for r in rows:
        result.setdefault(r["scale"], []).append(r)
    return result


def generate_single_chord_pairs(scales: dict) -> list[dict]:
    """Einzelner Akkord → MIDI-Noten + write_pattern."""
    pairs = []
    VOICINGS = [
        (3, "mittleres Voicing (3. Oktave)"),
        (4, "normales Voicing (4. Oktave)"),
        (5, "hohes Voicing (5. Oktave)"),
    ]

    for scale_name, chords in scales.items():
        for c in chords:
            base = c["base_notes"]
            for octave, voicing_label in VOICINGS:
                notes = transpose_to_octave(base, octave)
                nj = chord_to_notes_json(notes)
                notes_str = format_notes_compact(nj)

                # Q: Schreibe Akkord als MIDI
                pairs.append({
                    "prompt": f"Schreibe {c['chord_de']} als MIDI ({voicing_label}, 1/16 Quantisierung, 1 Takt)",
                    "completion": json.dumps({
                        "tool": "write_pattern",
                        "notes": json.dumps(nj),
                        "description": f"{c['chord_de']} ({c['dn']} in {scale_name}, {c['quality']})",
                    }, ensure_ascii=False),
                    "source": "format_chord_midi",
                })

                # Kompaktere Notation für Übersicht
                pairs.append({
                    "prompt": f"Wie lautet {c['chord_de']} in MIDI-Noten ({voicing_label})?",
                    "completion": notes_str,
                    "source": "format_chord_notes",
                })

    return pairs


def generate_progression_write_pattern(scales: dict) -> list[dict]:
    """Akkord-Progressionen → write_pattern mit mehreren Akkorden."""
    pairs = []

    PROGRESSIONS = [
        ([1, 4, 5, 1],    "I-IV-V-I", 16),
        ([2, 5, 1],       "II-V-I",   16),
        ([1, 5, 6, 4],    "I-V-VI-IV", 16),
        ([1, 6, 4, 5],    "I-VI-IV-V", 16),
        ([6, 4, 1, 5],    "VI-IV-I-V", 16),
    ]

    for scale_name, chords in scales.items():
        deg_map = {c["degree"]: c for c in chords}

        for deg_prog, roman, steps_each in PROGRESSIONS:
            chord_data = [deg_map.get(d) for d in deg_prog]
            if any(cd is None for cd in chord_data):
                continue

            all_notes_json = []
            step = 0
            chord_names = []
            for cd in chord_data:
                notes = transpose_to_octave(cd["base_notes"], 4)
                nj = chord_to_notes_json(notes, step=step, duration=steps_each)
                all_notes_json.extend(nj)
                chord_names.append(cd["chord_de"])
                step += steps_each

            chord_seq = " → ".join(chord_names)
            pairs.append({
                "prompt": (
                    f"Schreibe eine {roman}-Progression in {scale_name}, "
                    f"je {steps_each} Steps, 1/16 Quantisierung"
                ),
                "completion": json.dumps({
                    "tool": "write_pattern",
                    "notes": json.dumps(all_notes_json),
                    "description": f"{roman}: {chord_seq}",
                }, ensure_ascii=False),
                "source": "format_progression",
            })

    return pairs


def generate_scale_melody_pairs(s) -> list[dict]:
    """Tonleiter-Melodien (aufsteigend/absteigend) → write_pattern."""
    pairs = []

    scale_notes = s.run("""
        MATCH (sc:Scale)
        RETURN sc.name_de AS scale, sc.name_en AS scale_en, sc.notes AS notes
    """).data()

    for row in scale_notes:
        base_notes = row["notes"]
        if not base_notes:
            continue

        # C-Basis ist 0–11 (Pitch-Klassen), auf Oktave 4 bringen
        notes_oct4 = [n + 60 - base_notes[0] for n in base_notes]
        notes_oct4_up = notes_oct4 + [notes_oct4[0] + 12]  # Oktave Schluss

        # Aufsteigende Melodie
        asc_json = [
            {"pitch": p, "step": i * 4, "duration": 4, "velocity": 0.75, "channel": 0}
            for i, p in enumerate(notes_oct4_up)
        ]
        pairs.append({
            "prompt": f"Schreibe eine aufsteigende {row['scale']}-Tonleiter als MIDI (je 4 Steps)",
            "completion": json.dumps({
                "tool": "write_pattern",
                "notes": json.dumps(asc_json),
                "description": f"Aufsteigende {row['scale']}-Tonleiter",
            }, ensure_ascii=False),
            "source": "format_scale_melody",
        })

        # Absteigende Melodie
        desc_json = [
            {"pitch": p, "step": i * 4, "duration": 4, "velocity": 0.75, "channel": 0}
            for i, p in enumerate(reversed(notes_oct4_up))
        ]
        pairs.append({
            "prompt": f"Schreibe eine absteigende {row['scale']}-Tonleiter als MIDI (je 4 Steps)",
            "completion": json.dumps({
                "tool": "write_pattern",
                "notes": json.dumps(desc_json),
                "description": f"Absteigende {row['scale']}-Tonleiter",
            }, ensure_ascii=False),
            "source": "format_scale_melody",
        })

    return pairs


def generate_rhythm_variations(scales: dict) -> list[dict]:
    """Gleicher Akkord mit verschiedenen Rhythmen."""
    pairs = []

    RHYTHMS = [
        ("gerade Viertelnoten (je 4 Steps)", [0, 4, 8, 12], 4),
        ("punktierte Achtel + Sechzehntel (3+1 Steps)", [0, 3, 6, 9], 3),
        ("Synkopen (Offbeat, Achtel)", [2, 6, 10, 14], 2),
        ("ganze Note (16 Steps)", [0], 16),
    ]

    for scale_name, chords in scales.items():
        # Tonika jeder Tonart
        tonic = next((c for c in chords if c["degree"] == 1), None)
        if not tonic:
            continue

        base_notes = transpose_to_octave(tonic["base_notes"], 4)

        for rhythm_name, steps, dur in RHYTHMS:
            nj = []
            for step in steps:
                nj.extend(chord_to_notes_json(base_notes, step=step, duration=dur))

            pairs.append({
                "prompt": (
                    f"Schreibe {tonic['chord_de']} mit {rhythm_name} "
                    f"in 16 Steps (1/16 Quantisierung)"
                ),
                "completion": json.dumps({
                    "tool": "write_pattern",
                    "notes": json.dumps(nj),
                    "description": f"{tonic['chord_de']} / {rhythm_name}",
                }, ensure_ascii=False),
                "source": "format_rhythm",
            })

    return pairs


def generate_arp_pairs(scales: dict) -> list[dict]:
    """Arpeggio-Muster → einzelne Noten sequenziell."""
    pairs = []

    ARP_PATTERNS = [
        ("aufsteigendes Arpeggio", lambda n: n),
        ("absteigendes Arpeggio", lambda n: list(reversed(n))),
        ("Außen-zu-Innen (outside-in)", lambda n: (
            [n[0], n[-1], n[1], n[-2]] if len(n) >= 4 else n
        )),
    ]

    for scale_name, chords in scales.items():
        # Nur Tonika + Dominante
        for deg in [1, 5]:
            chord = next((c for c in chords if c["degree"] == deg), None)
            if not chord:
                continue

            base_notes = transpose_to_octave(chord["base_notes"], 4)

            for arp_name, arp_fn in ARP_PATTERNS:
                arp_order = arp_fn(base_notes)
                steps_per_note = 4
                nj = [
                    {"pitch": p, "step": i * steps_per_note,
                     "duration": steps_per_note, "velocity": 0.75, "channel": 0}
                    for i, p in enumerate(arp_order)
                ]

                pairs.append({
                    "prompt": (
                        f"Schreibe ein {arp_name} von {chord['chord_de']} "
                        f"(je 4 Steps, 1/16)"
                    ),
                    "completion": json.dumps({
                        "tool": "write_pattern",
                        "notes": json.dumps(nj),
                        "description": f"{chord['chord_de']} {arp_name}",
                    }, ensure_ascii=False),
                    "source": "format_arp",
                })

    return pairs


def main():
    print("=== Format-Paare generieren (Ebene 2) ===\n")

    with session() as s:
        scales = load_chords_per_scale(s)
        scale_mel = generate_scale_melody_pairs(s)

    print(f"  Geladen: {len(scales)} Tonarten")

    pairs = []

    chord_pairs = generate_single_chord_pairs(scales)
    pairs += chord_pairs
    print(f"  Akkord→MIDI-Paare:       {len(chord_pairs)}")

    prog_pairs = generate_progression_write_pattern(scales)
    pairs += prog_pairs
    print(f"  Progressions-Paare:      {len(prog_pairs)}")

    pairs += scale_mel
    print(f"  Tonleiter-Melodie-Paare: {len(scale_mel)}")

    rhythm_pairs = generate_rhythm_variations(scales)
    pairs += rhythm_pairs
    print(f"  Rhythmus-Paare:          {len(rhythm_pairs)}")

    arp_pairs = generate_arp_pairs(scales)
    pairs += arp_pairs
    print(f"  Arpeggio-Paare:          {len(arp_pairs)}")

    random.seed(42)
    random.shuffle(pairs)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"\n✅ {len(pairs)} Paare → {OUTPUT}")

    # Stichprobe
    print("\n  Beispiele:")
    sample = random.sample(pairs, min(5, len(pairs)))
    for p in sample:
        print(f"  [{p['source']}]")
        print(f"    Q: {p['prompt']}")
        compl = p['completion']
        if len(compl) > 140:
            compl = compl[:137] + "..."
        print(f"    A: {compl}")


if __name__ == "__main__":
    main()
