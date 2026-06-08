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


def arpeggio_over_bar(notes: list[int], velocity: float = 0.8,
                       steps_per_note: int = 2) -> list[dict]:
    """Arpeggiert Akkord-Noten zyklisch über 16 Steps (füllt den Takt).

    Für ein Triad (3 Noten): 16 // 2 = 8 Slots → ~8 Noten (2-3 Zyklen).
    Für einen 4-Noten-Akkord: 16 // 2 = 8 Slots → 8 Noten (2 Zyklen).
    Jede Note hat definierte Länge → kein Runaway.
    """
    result = []
    step = 0
    i = 0
    while step < 16:
        result.append({
            "pitch":    notes[i % len(notes)],
            "step":     step,
            "duration": steps_per_note,
            "velocity": round(velocity, 2),
            "channel":  0,
        })
        step += steps_per_note
        i += 1
    return result


def generate_single_chord_pairs(scales: dict) -> list[dict]:
    """Einzelner Akkord → arpeggiertes write_pattern über 1 Takt (≥8 Noten)."""
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
                # Arpeggio über Bar — steps_per_note=1: 16 Noten (füllt jeden 16tel-Step)
                nj = arpeggio_over_bar(notes, velocity=0.8, steps_per_note=1)
                notes_str = format_notes_compact(nj)

                pairs.append({
                    "prompt": (
                        f"Schreibe {c['chord_de']} als MIDI-Arpeggio "
                        f"({voicing_label}, 1/16 Quantisierung, 1 Takt)"
                    ),
                    "completion": json.dumps({
                        "tool": "write_pattern",
                        "notes": json.dumps(nj),
                        "description": f"{c['chord_de']} ({c['dn']} in {scale_name}, {c['quality']}) — Arpeggio",
                    }, ensure_ascii=False),
                    "source": "format_chord_midi",
                })

                pairs.append({
                    "prompt": f"Wie lautet {c['chord_de']} als Arpeggio-Sequenz ({voicing_label})?",
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
    """Tonleiter-Melodien auf+ab in 2 Steps → 14-16 Noten pro Pair."""
    pairs = []

    scale_notes = s.run("""
        MATCH (sc:Scale)
        RETURN sc.name_de AS scale, sc.name_en AS scale_en, sc.notes AS notes
    """).data()

    for row in scale_notes:
        base_notes = row["notes"]
        if not base_notes:
            continue

        notes_oct4 = [n + 60 - base_notes[0] for n in base_notes]
        notes_oct4_up = notes_oct4 + [notes_oct4[0] + 12]  # Oktave-Schluss (8 Noten)

        # Aufsteigend + absteigend in 2-Step-Abständen (16 Noten)
        combined = notes_oct4_up + list(reversed(notes_oct4_up[:-1]))  # 8 + 7 = 15 Noten
        combined_json = [
            {"pitch": p, "step": i * 2, "duration": 2, "velocity": 0.75, "channel": 0}
            for i, p in enumerate(combined)
        ]
        pairs.append({
            "prompt": f"Schreibe eine {row['scale']}-Tonleiter auf und ab als MIDI (je 2 Steps)",
            "completion": json.dumps({
                "tool": "write_pattern",
                "notes": json.dumps(combined_json),
                "description": f"{row['scale']}-Tonleiter auf+ab",
            }, ensure_ascii=False),
            "source": "format_scale_melody",
        })

        # Aufsteigende Melodie (7 Steps für 7-Ton-Skalen, 4 Steps Abstand)
        asc_json = [
            {"pitch": p, "step": i * 2, "duration": 2, "velocity": 0.75, "channel": 0}
            for i, p in enumerate(notes_oct4_up)
        ]
        pairs.append({
            "prompt": f"Schreibe eine aufsteigende {row['scale']}-Tonleiter als MIDI (je 2 Steps)",
            "completion": json.dumps({
                "tool": "write_pattern",
                "notes": json.dumps(asc_json),
                "description": f"Aufsteigende {row['scale']}-Tonleiter",
            }, ensure_ascii=False),
            "source": "format_scale_melody",
        })

    return pairs


def generate_rhythm_variations(scales: dict) -> list[dict]:
    """Gleicher Akkord mit verschiedenen Rhythmen — je mind. 12 Noten."""
    pairs = []

    RHYTHMS = [
        ("gerade Viertelnoten (je 4 Steps)", [0, 4, 8, 12], 4),
        ("punktierte Achtel + Sechzehntel (3+1 Steps)", [0, 3, 6, 9, 12], 3),
        ("Synkopen (Offbeat, Achtel)", [2, 6, 10, 14], 2),
        # "ganze Note" → 4× Akkordwechsel je 4 Steps (statt 1× mit 16 Steps)
        ("Akkordwechsel alle 4 Beats (4×)", [0, 4, 8, 12], 4),
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
    """Arpeggio-Muster → 2 Zyklen über 1 Takt (16 Steps, ≥ 6 Noten)."""
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
                # 1 Step pro Note → exakt 16 Noten (füllt alle 16tel-Steps)
                nj = []
                for step in range(16):
                    p = arp_order[step % len(arp_order)]
                    nj.append({
                        "pitch": p, "step": step,
                        "duration": 1, "velocity": 0.75, "channel": 0,
                    })

                pairs.append({
                    "prompt": (
                        f"Schreibe ein {arp_name} von {chord['chord_de']} "
                        f"(16 Steps, je 1 Step, 1/16)"
                    ),
                    "completion": json.dumps({
                        "tool": "write_pattern",
                        "notes": json.dumps(nj),
                        "description": f"{chord['chord_de']} {arp_name} — 16 Steps",
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
