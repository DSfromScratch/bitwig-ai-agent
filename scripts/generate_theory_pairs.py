"""
Ebene 1 Trainingsdaten: Musiktheorie Q&A-Paare aus Neo4j generieren.

Output: data/training/theory_pairs.jsonl
Format: {"prompt": "...", "completion": "...", "source": "theory"}

Generiert ~3.000–8.000 Paare aus 24 Tonarten × 7 Akkorden × Progressionen.
"""
from __future__ import annotations
import os, sys, json, random, itertools
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.knowledge.neo4j_graph import session

OUTPUT = Path("data/training/theory_pairs.jsonl")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

DEGREE_NAMES = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII"}
FUNCTION_DE = {
    "tonic":       "Tonika (Ruhepol)",
    "supertonic":  "Supertonika (Spannung → Dominant)",
    "mediant":     "Mediante",
    "subdominant": "Subdominante",
    "dominant":    "Dominante (Spannung → Tonika)",
    "submediant":  "Submediant (Tonika-Parallele)",
    "leading":     "Leitton (→ Tonika)",
}


def load_all_scales(s) -> list[dict]:
    return s.run("""
        MATCH (sc:Scale)-[r:DIATONIC_CHORD]->(c:Chord)
        RETURN sc.name_de AS scale, sc.name_en AS scale_en,
               r.degree AS degree, r.degree_name AS dn,
               r.function AS fn, c.name_de AS chord, c.name_en AS chord_en,
               c.quality AS quality
        ORDER BY sc.name_de, r.degree
    """).data()


def load_resolutions(s) -> list[dict]:
    return s.run("""
        MATCH (a:Chord)-[r:RESOLVES_TO]->(b:Chord)
        RETURN r.scale AS scale, a.name_de AS von, b.name_de AS nach,
               r.strength AS strength, r.label AS label,
               r.from_degree AS from_d, r.to_degree AS to_d
        ORDER BY r.scale, r.strength DESC
    """).data()


def group_by_scale(rows: list[dict]) -> dict[str, list[dict]]:
    scales: dict[str, list] = {}
    for r in rows:
        scales.setdefault(r["scale"], []).append(r)
    return scales


def scale_chords_str(chords: list[dict]) -> str:
    return ", ".join(
        f"{c['chord']}({c['dn']})" for c in sorted(chords, key=lambda x: x["degree"])
    )


def generate_scale_chord_pairs(scales: dict) -> list[dict]:
    pairs = []
    for scale_name, chords in scales.items():
        chord_str = scale_chords_str(chords)

        # Q: Welche Akkorde sind diatonisch?
        pairs.append({
            "prompt": f"Welche Akkorde sind in {scale_name} diatonisch?",
            "completion": chord_str,
            "source": "theory_diatonic",
        })

        # Q: englische Variante
        en = chords[0].get("scale_en", "")
        if en:
            pairs.append({
                "prompt": f"Which chords are diatonic to {en}?",
                "completion": chord_str,
                "source": "theory_diatonic_en",
            })

        # Q: pro Akkord — welche Stufe?
        for c in chords:
            pairs.append({
                "prompt": f"Welche Stufe hat {c['chord']} in {scale_name}?",
                "completion": f"{c['dn']} — {FUNCTION_DE.get(c['fn'], c['fn'])}",
                "source": "theory_degree",
            })

        # Q: Tonika, Dominante, Subdominante
        for fn, fn_de in FUNCTION_DE.items():
            matches = [c for c in chords if c["fn"] == fn]
            if matches:
                names = " / ".join(c["chord"] for c in matches)
                pairs.append({
                    "prompt": f"Welcher Akkord ist die {fn_de.split(' ')[0]} in {scale_name}?",
                    "completion": names,
                    "source": "theory_function",
                })

    return pairs


def generate_resolution_pairs(resolutions: list[dict]) -> list[dict]:
    pairs = []

    # Nach Tonart gruppieren
    by_scale: dict[str, list] = {}
    for r in resolutions:
        by_scale.setdefault(r["scale"], []).append(r)

    for scale, rels in by_scale.items():
        # Top-3 Auflösungen für diese Tonart
        top = sorted(rels, key=lambda x: -x["strength"])[:6]
        top_str = "; ".join(
            f"{r['von']} → {r['nach']} ({r['label']}, Stärke {r['strength']:.2f})"
            for r in top
        )
        pairs.append({
            "prompt": f"Welche Akkordauflösungen gibt es in {scale}?",
            "completion": top_str,
            "source": "theory_resolutions",
        })

        # Pro Akkord: Wohin löst er auf?
        by_source: dict[str, list] = {}
        for r in rels:
            by_source.setdefault(r["von"], []).append(r)

        for chord, targets in by_source.items():
            strongest = max(targets, key=lambda x: x["strength"])
            pairs.append({
                "prompt": f"Was folgt auf {chord} in {scale}?",
                "completion": (
                    f"Stärkste Auflösung: {strongest['nach']} "
                    f"({strongest['label']}, Stärke {strongest['strength']:.2f})"
                ),
                "source": "theory_next_chord",
            })

    return pairs


def generate_progression_pairs(scales: dict) -> list[dict]:
    """I-IV-V-I, ii-V-I, I-VI-IV-V und andere Standard-Progressionen."""
    pairs = []

    PROGRESSIONS = [
        ([1, 4, 5, 1],    "I-IV-V-I (klassische Kadenz)"),
        ([2, 5, 1],       "II-V-I (Jazz-Kadenz)"),
        ([1, 5, 6, 4],    "I-V-VI-IV (Pop-Progression)"),
        ([1, 6, 4, 5],    "I-VI-IV-V (doo-wop)"),
        ([6, 4, 1, 5],    "VI-IV-I-V (relative minor)"),
        ([1, 4, 6, 5],    "I-IV-VI-V"),
        ([1, 2, 5, 1],    "I-II-V-I"),
        ([1, 3, 4, 5],    "I-III-IV-V"),
        ([1, 5, 4, 1],    "I-V-IV-I (Plagal)"),
    ]

    for scale_name, chords in scales.items():
        deg_map = {c["degree"]: c["chord"] for c in chords}

        for deg_prog, label in PROGRESSIONS:
            chord_names = [deg_map.get(d, "?") for d in deg_prog]
            if "?" in chord_names:
                continue
            roman = "-".join(DEGREE_NAMES[d] for d in deg_prog)
            chord_str = " → ".join(chord_names)
            pairs.append({
                "prompt": f"Spiele eine {roman}-Progression in {scale_name}",
                "completion": chord_str,
                "source": "theory_progression",
            })

    return pairs


def generate_cadence_pairs(scales: dict, resolutions: list[dict]) -> list[dict]:
    """Kadenz-Erkennung: Welche Kadenz liegt vor?"""
    pairs = []
    by_scale_res: dict[str, dict] = {}
    for r in resolutions:
        by_scale_res.setdefault(r["scale"], {})[
            (r["from_d"], r["to_d"])
        ] = r

    CADENCE_NAMES = {
        (5, 1): "Authentische Kadenz (V→I, volle Schluss-Wirkung)",
        (4, 1): "Plagale Kadenz (IV→I, 'Amen'-Kadenz, ruhiger)",
        (5, 6): "Trugschluss (V→VI, täuscht Auflösung vor)",
        (2, 5): "Halbkadenz auf der Dominante (II→V)",
        (7, 1): "Leitton-Auflösung (VII→I, sehr starke Spannung)",
    }

    for scale, rels in by_scale_res.items():
        scale_chords = scales.get(scale, [])
        deg_map = {c["degree"]: c["chord"] for c in scale_chords}

        for (from_d, to_d), cad_name in CADENCE_NAMES.items():
            from_chord = deg_map.get(from_d)
            to_chord   = deg_map.get(to_d)
            if not from_chord or not to_chord:
                continue

            pairs.append({
                "prompt": f"Was ist {from_chord} → {to_chord} in {scale}?",
                "completion": cad_name,
                "source": "theory_cadence",
            })

    return pairs


def main():
    print("=== Theorie-Paare generieren (Ebene 1) ===\n")

    with session() as s:
        all_rows = load_all_scales(s)
        resolutions = load_resolutions(s)

    scales = group_by_scale(all_rows)
    print(f"  Geladen: {len(scales)} Tonarten, {len(all_rows)} Akkord-Relationen, "
          f"{len(resolutions)} Auflösungen")

    pairs = []
    pairs += generate_scale_chord_pairs(scales)
    print(f"  Tonart/Akkord-Paare:    {len(pairs)}")

    res_pairs = generate_resolution_pairs(resolutions)
    pairs += res_pairs
    print(f"  Auflösungs-Paare:       {len(res_pairs)}")

    prog_pairs = generate_progression_pairs(scales)
    pairs += prog_pairs
    print(f"  Progressions-Paare:     {len(prog_pairs)}")

    cad_pairs = generate_cadence_pairs(scales, resolutions)
    pairs += cad_pairs
    print(f"  Kadenz-Paare:           {len(cad_pairs)}")

    # Leichte Shuffle für Training
    random.seed(42)
    random.shuffle(pairs)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"\n✅ {len(pairs)} Paare → {OUTPUT}")

    # Stichprobe
    print("\n  Beispiele:")
    for p in pairs[:5]:
        print(f"  [{p['source']}]")
        print(f"    Q: {p['prompt']}")
        print(f"    A: {p['completion'][:120]}")


if __name__ == "__main__":
    main()
