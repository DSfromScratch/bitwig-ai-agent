"""
Schritt 1: Musiktheorie-Graph in Neo4j vervollständigen.

- DIATONIC_CHORD: degree_name (I/II/…) + function (tonic/dominant/…) hinzufügen
- RESOLVES_TO: Stimmführungs-Kanten zwischen Akkorden pro Tonart anlegen
- Läuft idempotent — kann mehrfach ausgeführt werden
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.knowledge.neo4j_graph import session

# Römische Grade
DEGREE_NAMES = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII"}

# Harmonische Funktion pro Stufe (Dur + Moll etwas unterschiedlich — vereinfacht)
DEGREE_FUNCTION = {
    1: "tonic",        # I  — Ruhepol
    2: "supertonic",   # II — Spannung → Dominant
    3: "mediant",      # III
    4: "subdominant",  # IV — Subdominante
    5: "dominant",     # V  — Spannung → Tonika
    6: "submediant",   # VI — Tonika-Parallele
    7: "leading",      # VII — Leitton → Tonika
}

# Stimmführungs-Regeln: von Stufe X → Stufe Y, Stärke 0.0–1.0
# (gelten für Dur und Moll gleichermassen)
RESOLUTION_RULES: list[tuple[int, int, float, str]] = [
    # (von, nach, stärke, name)
    (5, 1, 1.0,  "authentic cadence V→I"),
    (7, 1, 0.9,  "leading tone VII→I"),
    (4, 1, 0.75, "plagal cadence IV→I"),
    (2, 5, 0.85, "II→V (pre-dominant)"),
    (4, 5, 0.80, "IV→V (subdominant→dominant)"),
    (6, 4, 0.60, "VI→IV"),
    (6, 2, 0.55, "VI→II"),
    (3, 6, 0.50, "III→VI (deceptive)"),
    (1, 4, 0.65, "I→IV (subdominant motion)"),
    (1, 5, 0.70, "I→V (dominant motion)"),
    (5, 6, 0.45, "deceptive cadence V→VI"),
    (2, 1, 0.40, "II→I (rare)"),
]


def update_degree_names(s) -> int:
    """Fügt degree_name und function zu bestehenden DIATONIC_CHORD-Relationen hinzu."""
    updated = 0
    for deg, name in DEGREE_NAMES.items():
        func = DEGREE_FUNCTION[deg]
        result = s.run("""
            MATCH ()-[r:DIATONIC_CHORD]->()
            WHERE r.degree = $deg AND (r.degree_name IS NULL OR r.function IS NULL)
            SET r.degree_name = $name, r.function = $func
            RETURN count(r) AS n
        """, deg=deg, name=name, func=func).single()["n"]
        updated += result
    return updated


def create_resolves_to(s) -> int:
    """Legt RESOLVES_TO-Kanten zwischen Akkorden pro Tonart an."""
    created = 0
    scales = s.run("MATCH (sc:Scale) RETURN sc.name_de AS name").data()

    for sc_row in scales:
        scale_name = sc_row["name"]

        # Alle 7 diatonischen Akkorde dieser Tonart mit ihrer Stufe laden
        chords = s.run("""
            MATCH (sc:Scale {name_de: $name})-[r:DIATONIC_CHORD]->(c:Chord)
            RETURN r.degree AS degree, c.name_de AS chord_name
            ORDER BY r.degree
        """, name=scale_name).data()

        degree_to_chord = {row["degree"]: row["chord_name"] for row in chords}

        for (from_deg, to_deg, strength, label) in RESOLUTION_RULES:
            from_chord = degree_to_chord.get(from_deg)
            to_chord   = degree_to_chord.get(to_deg)
            if not from_chord or not to_chord:
                continue

            result = s.run("""
                MATCH (a:Chord {name_de: $from_chord})
                MATCH (b:Chord {name_de: $to_chord})
                MERGE (a)-[r:RESOLVES_TO {scale: $scale}]->(b)
                ON CREATE SET r.strength = $strength,
                              r.label    = $label,
                              r.from_degree = $from_deg,
                              r.to_degree   = $to_deg
                RETURN count(r) AS n
            """, from_chord=from_chord, to_chord=to_chord,
                 scale=scale_name, strength=strength, label=label,
                 from_deg=from_deg, to_deg=to_deg).single()["n"]
            created += result

    return created


def main():
    print("=== Musiktheorie-Graph vervollständigen ===\n")
    with session() as s:
        # 1. Degree-Namen updaten
        n = update_degree_names(s)
        print(f"✓ DIATONIC_CHORD: {n} Relationen mit degree_name + function aktualisiert")

        # Verifikation
        sample = s.run("""
            MATCH (sc:Scale {name_de: "Fis-Moll"})-[r:DIATONIC_CHORD]->(c:Chord)
            RETURN r.degree AS d, r.degree_name AS dn, r.function AS fn, c.name_de AS chord
            ORDER BY r.degree
        """).data()
        print("\n  Fis-Moll Beispiel:")
        for r in sample:
            print(f"    {r['dn']:<5} ({r['fn']:<15}) → {r['chord']}")

        # 2. RESOLVES_TO anlegen
        print("\n  Lege RESOLVES_TO-Kanten an …")
        n = create_resolves_to(s)
        print(f"✓ RESOLVES_TO: {n} Kanten erstellt/bestätigt")

        # Verifikation
        sample2 = s.run("""
            MATCH (a:Chord)-[r:RESOLVES_TO {scale: "Fis-Moll"}]->(b:Chord)
            RETURN a.name_de AS von, b.name_de AS nach, r.strength AS st, r.label AS lbl
            ORDER BY r.strength DESC
            LIMIT 6
        """).data()
        print("\n  Fis-Moll Auflösungen (stärkste zuerst):")
        for r in sample2:
            print(f"    {r['von']:<15} → {r['nach']:<15}  stärke={r['st']:.2f}  ({r['lbl']})")

    print("\n✅ Theorie-Graph vollständig")


if __name__ == "__main__":
    main()
