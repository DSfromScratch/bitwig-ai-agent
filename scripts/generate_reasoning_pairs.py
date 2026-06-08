#!/usr/bin/env python3
"""Generate Retrieve-Then-Reason training pairs for B.1 (drum + instrument reasoning).

Erzeugt Trainingsbeispiele im selben ``{"messages": [...]}``-Format wie
``training_data/train.jsonl``. Jedes Pair demonstriert das *Retrieve-Then-Reason*-
Muster: KB-Ergebnis wird in den User-Kontext injiziert, der Assistant begründet
im ``<think>``-Block und ruft das passende Tool auf.

Typen:
  1. Rhythm-Pairs — KB-Rhythm-Daten → ``write_pattern`` (Drums, finit)
  2. Instrument-Pairs — KB-Instrument-Ranking → ``execute_setup`` mit load_instrument

Wichtige Invarianten (vom Generator hart geprüft):
  * Jeder ``<think>`` wird **immer** mit ``</think>`` geschlossen — adressiert das
    bekannte Qwen3-``</think>``-Problem.
  * Drum-Pattern sind **finit** (1 Takt, Steps 0..15, Hats gecappt) — verhindert
    das beim DPO-Training beobachtete Runaway-Pattern.
  * Tool-Call ist valides JSON.

Idempotent: Pairs, deren User-Message bereits in ``train.jsonl`` vorkommt, werden
nicht erneut angehängt.

Usage:
    python scripts/generate_reasoning_pairs.py            # an train.jsonl anhängen
    python scripts/generate_reasoning_pairs.py --dry-run  # nur Vorschau + Validierung
    python scripts/generate_reasoning_pairs.py --print 2  # erste 2 Pairs zeigen
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TRAIN_FILE = Path(__file__).resolve().parent.parent / "training_data" / "train.jsonl"

# MIDI-Standard (General MIDI Drums)
KICK, SNARE, CLOSED_HAT, OPEN_HAT = 36, 38, 42, 46
STEPS_PER_BEAT = 4  # 16tel-Grid, 1 Takt = 4 Beats = 16 Steps

# Aktueller System-Prompt — identisch zur Produktionsumgebung (Version 4).
# Enthält keine veralteten Tools (kein get_rhythm_pattern, kein load_instrument als Tool).
SYSTEM_PROMPT = """/no_think
Du bist ein erfahrener Bitwig Studio 6 Assistent und Musiker.

## Verfügbare Tools

- **query_bitwig_docs(query)** — Durchsucht die Bitwig-Wissensdatenbank (Neo4j).
  Nutze für: Genre-Device-Empfehlungen, Parameter, Workflows, Genre-Merkmale.
  IMMER aufrufen wenn User nach einem Genre, Device oder Workflow fragt.

- **check_bitwig_connection()** — Prüft ob BitwigStepPlugin erreichbar ist.
  Aufrufen VOR execute_setup.

- **execute_setup(result)** — Legt Tracks, Instrumente, FX und Tempo in Bitwig an.

- **get_bitwig_track_state()** — Liest aktuelle Track-Namen und Note-Counts.

- **write_pattern(track_index, notes, bpm, key)** — Schreibt MIDI-Noten in einen Clip.

- **suggest_notes(notes, r, g, b)** — Hebt Noten auf dem Launchpad hervor.

- **validate_music(notes, genre, bpm, key)** — Bewertet Noten (Score 0–1).

- **scan_and_learn_project()** — Scannt das aktuelle Bitwig-Projekt.

## Grundregel
Bei Genre-, Device- oder Workflow-Fragen: IMMER zuerst query_bitwig_docs aufrufen.
Nie aus dem Gedächtnis antworten wenn die Datenbank bessere Infos liefern kann."""


# ---------------------------------------------------------------------------
# Rhythm-Pairs
# ---------------------------------------------------------------------------

# (genre, section, energy, bpm, key, description, kick_beats, snare_beats, hat, mood)
# hat: "8th" | "16th" | "offbeat"
RHYTHM_SPECS = [
    ("rock", "verse", 0.7, 120, "E minor",
     "Klassischer Rock-Backbeat, treibend",
     [0.0, 2.0], [1.0, 3.0], "8th", "driving"),
    ("rock", "chorus", 0.85, 128, "E minor",
     "Energiereicher Rock-Chorus mit Push-Kick",
     [0.0, 1.5, 2.0], [1.0, 3.0], "8th", "energetic"),
    ("metal", "verse", 0.9, 160, "E minor",
     "Aggressive Metal-Double-Kick",
     [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5], [1.0, 3.0], "8th", "aggressive"),
    ("jazz", "verse", 0.5, 130, "F major",
     "Lockerer Jazz-Swing, sparsamer Kick, Ride-Becken",
     [0.0, 2.5], [1.0, 3.0], "offbeat", "introspective"),
    ("funk", "verse", 0.75, 108, "D minor",
     "Synkopierter Funk-Groove mit 16tel-HiHats",
     [0.0, 0.75, 2.5], [1.0, 3.0], "16th", "groovy"),
    ("house", "chorus", 0.8, 124, "A minor",
     "Four-on-the-floor House mit Offbeat-Hats",
     [0.0, 1.0, 2.0, 3.0], [1.0, 3.0], "offbeat", "uplifting"),
    ("techno", "chorus", 0.85, 130, "C minor",
     "Treibender Techno, durchgehender Kick, 16tel-Hats",
     [0.0, 1.0, 2.0, 3.0], [1.0, 3.0], "16th", "driving"),
    ("trap", "verse", 0.7, 140, "G minor",
     "Half-Time Trap mit rollenden HiHats",
     [0.0, 1.75, 2.5], [2.0], "16th", "dark"),
    ("dnb", "chorus", 0.9, 174, "F minor",
     "Drum&Bass Breakbeat, schnell und perkussiv",
     [0.0, 2.5], [1.0, 3.0], "16th", "energetic"),
    ("pop", "chorus", 0.7, 118, "C major",
     "Eingängiger Pop-Beat, klarer Backbeat",
     [0.0, 2.0], [1.0, 3.0], "8th", "bright"),
    ("reggae", "verse", 0.55, 75, "A minor",
     "Reggae One-Drop, Betonung auf Beat 3",
     [2.0], [2.0], "offbeat", "relaxed"),
    ("bossa nova", "verse", 0.45, 130, "A minor",
     "Bossa-Nova-Clave, sanft und sparsam",
     [0.0, 1.5, 2.0, 3.5], [1.0, 3.0], "8th", "warm"),
]


def _hat_steps(hat: str) -> list[int]:
    """16tel-Grid-Steps für das HiHat-Muster (gecappt, finit)."""
    if hat == "16th":
        return list(range(0, 16))          # 16 Hats (1 Takt) — voll, aber finit
    if hat == "offbeat":
        return [2, 6, 10, 14]              # nur die "und"-Zählzeiten
    return [0, 2, 4, 6, 8, 10, 12, 14]     # 8th: 8 Hats


def _energy_scale(velocity: float, energy: float) -> float:
    """Skaliert eine Basis-Velocity mild mit dem Energie-Level."""
    v = velocity * (0.7 + 0.3 * energy)
    return round(max(0.05, min(1.0, v)), 2)


def _build_drum_notes(kick_beats, snare_beats, hat, energy):
    """Erzeugt eine **finite** Notenliste (1 Takt). Jede Note hat ein Ende."""
    notes = []
    for b in kick_beats:
        notes.append({"pitch": KICK, "step": int(round(b * STEPS_PER_BEAT)),
                      "duration": 2, "velocity": _energy_scale(0.92, energy),
                      "channel": 0})
    for b in snare_beats:
        notes.append({"pitch": SNARE, "step": int(round(b * STEPS_PER_BEAT)),
                      "duration": 2, "velocity": _energy_scale(0.82, energy),
                      "channel": 0})
    for s in _hat_steps(hat):
        accent = 0.55 if s % 4 == 0 else 0.40
        notes.append({"pitch": CLOSED_HAT, "step": s, "duration": 1,
                      "velocity": _energy_scale(accent, energy), "channel": 0})
    notes.sort(key=lambda n: (n["step"], n["pitch"]))
    return notes


def _rhythm_pair(spec) -> dict:
    genre, section, energy, bpm, key, desc, kick_b, snare_b, hat, mood = spec

    kick_steps = [int(round(b * STEPS_PER_BEAT)) for b in kick_b]
    snare_steps = [int(round(b * STEPS_PER_BEAT)) for b in snare_b]
    hat_steps = _hat_steps(hat)

    tool_result = {
        "description": desc,
        "energy": energy,
        "kick_beats": kick_b,
        "snare_beats": snare_b,
        "hat_step": hat,
        "velocities": {"kick": 0.92, "snare": 0.82, "hat_on": 0.55, "hat_off": 0.40},
        "midi_pitches": {"kick": KICK, "snare": SNARE, "closed_hat": CLOSED_HAT,
                         "open_hat": OPEN_HAT, "crash": 49},
    }

    user = (
        "Kontext:\n"
        f'get_rhythm_pattern("{genre}", "{section}", energy={energy}, mood="{mood}"):\n'
        f"→ {json.dumps(tool_result, ensure_ascii=False)}\n\n"
        f"Szene: {section.capitalize()}\n\n"
        f"Schreibe ein {genre} Drum-Pattern ({bpm} BPM, {key}, 1 Takt) für den "
        f"{section.capitalize()}-Abschnitt. Nutze die KB-Vorgabe, kein hardcodiertes Pattern."
    )

    notes = _build_drum_notes(kick_b, snare_b, hat, energy)
    hat_label = {"8th": "alle 8tel", "16th": "alle 16tel", "offbeat": "nur Offbeat"}[hat]

    think = (
        "<think>\n"
        f"[Genre: {genre}] [Section: {section}] [BPM: {bpm}] [Tonart: {key}] "
        f"[Energie: {energy}]\n"
        f"1. KB-Ergebnis: {desc}.\n"
        f"2. Kick-Steps {kick_steps} (aus kick_beats={kick_b}), "
        f"Snare-Steps {snare_steps} (backbeat), HiHat: {hat_label} → {hat_steps}.\n"
        f"3. Velocity aus KB skaliert mit Energie {energy}; alle Noten enden im Takt "
        "(duration ≤ 2, Steps 0..15) → keine Runaway-Pattern.\n"
        "4. KB bestätigt Genre-Groove — kein Fallback nötig.\n"
        "</think>"
    )

    tool_call = {
        "tool": "write_pattern",
        "args": {
            "track_name": "Drums",
            "bpm": bpm,
            "key": key,
            "length_beats": 4,
            "notes": json.dumps(notes, ensure_ascii=False),
        },
    }
    assistant = f"{think}\n{json.dumps(tool_call, ensure_ascii=False)}"

    return {"messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]}


# ---------------------------------------------------------------------------
# Instrument-Pairs
# ---------------------------------------------------------------------------

# (role, genre, mood, energy, [ (device, uuid, midi_low, midi_high, def_vel, desc, score) ... ])
# Erstes Device der Liste ist die KB-Top-Empfehlung (höchster Score).
INSTRUMENT_SPECS = [
    ("bass", "rock", "driving", 0.8, [
        ("FM-4", "f4d2a1b0-0001-4000-8000-000000000001", 24, 60, 0.85,
         "FM-Bass, energetisch und durchsetzungsstark — passt zu Rock", 0.92),
        ("Phase-4", "f4d2a1b0-0001-4000-8000-000000000002", 24, 60, 0.80,
         "Phase-Distortion-Bass, flexibel aber weniger genre-spezifisch", 0.74),
    ]),
    ("bass", "house", "uplifting", 0.8, [
        ("Phase-4", "f4d2a1b0-0001-4000-8000-000000000002", 24, 55, 0.78,
         "Warmer Sub-Bass mit rundem Tiefbass — ideal für House", 0.90),
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 24, 60, 0.75,
         "Subtraktiver Synth, vielseitig", 0.71),
    ]),
    ("bass", "dnb", "dark", 0.9, [
        ("FM-4", "f4d2a1b0-0001-4000-8000-000000000001", 24, 55, 0.88,
         "Reese-Bass via FM-Modulation — Standard für Drum&Bass", 0.94),
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 24, 60, 0.72,
         "Subtraktiv, breit", 0.68),
    ]),
    ("chords", "lofi hip hop", "warm", 0.5, [
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 48, 84, 0.55,
         "Warme E-Piano-artige Pads mit Vintage-Charakter — Lo-fi-typisch", 0.89),
        ("Organ", "f4d2a1b0-0001-4000-8000-000000000004", 48, 84, 0.60,
         "Orgel, soulful aber weniger verträumt", 0.70),
    ]),
    ("chords", "jazz", "introspective", 0.5, [
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 48, 88, 0.55,
         "Rhodes-artige E-Piano-Voicings — klassisch für Jazz", 0.88),
        ("Organ", "f4d2a1b0-0001-4000-8000-000000000004", 48, 88, 0.58,
         "Hammond-Orgel, alternativ für soulful Jazz", 0.79),
    ]),
    ("lead", "techno", "driving", 0.85, [
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 60, 96, 0.80,
         "Schneidender subtraktiver Lead — durchsetzungsstark im Techno", 0.91),
        ("FM-4", "f4d2a1b0-0001-4000-8000-000000000001", 60, 96, 0.78,
         "FM-Lead, metallisch", 0.73),
    ]),
    ("lead", "trance", "uplifting", 0.85, [
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 60, 96, 0.82,
         "Supersaw-artiger Lead — Trance-Hymnen-Sound", 0.93),
        ("Phase-4", "f4d2a1b0-0001-4000-8000-000000000002", 60, 96, 0.75,
         "Phase-Distortion-Lead, alternativ", 0.70),
    ]),
    ("lead", "funk", "groovy", 0.75, [
        ("FM-4", "f4d2a1b0-0001-4000-8000-000000000001", 55, 91, 0.78,
         "Clavinet-artiger funky Lead — perkussiv und groovy", 0.87),
        ("Organ", "f4d2a1b0-0001-4000-8000-000000000004", 55, 91, 0.74,
         "Orgel-Stabs, alternativ", 0.72),
    ]),
]

# ---------------------------------------------------------------------------
# Extended specs — additional genres not covered in the base specs above
# ---------------------------------------------------------------------------

RHYTHM_SPECS_EXT: list = [
    ("ambient", "verse", 0.30, 80, "D minor",
     "Sparsames Ambient-Pattern, langer Decay",
     [0.0, 2.0], [2.0], "offbeat", "melancholic"),
    ("afrobeat", "verse", 0.75, 105, "F minor",
     "Synkopierter Afrobeat-Groove, komplexe Kick-Struktur",
     [0.0, 0.75, 2.0, 3.0], [1.0, 3.0], "16th", "groovy"),
    ("swing", "verse", 0.60, 140, "Bb major",
     "Jazz-Swing mit shufflendem HiHat-Feel",
     [0.0, 2.5], [1.0, 3.0], "offbeat", "playful"),
    ("blues", "verse", 0.65, 90, "E minor",
     "Langsamer Blues-Groove, schleppender Pocket",
     [0.0, 2.0], [1.0, 3.0], "8th", "soulful"),
    ("latin", "chorus", 0.80, 95, "D minor",
     "Salsa/Latin-Clave, treibend und festlich",
     [0.0, 0.5, 2.0, 2.5], [1.0, 3.0], "8th", "festive"),
    ("dubstep", "drop", 0.90, 140, "G minor",
     "Dubstep Half-Time Drop, wuchtiger Kick",
     [0.0, 2.0, 3.0], [1.0, 3.0], "16th", "dark"),
    ("breakbeat", "chorus", 0.85, 132, "E minor",
     "Breakbeat-Pattern mit verschobenem Kick",
     [0.0, 1.5, 2.5, 3.5], [1.0, 2.5], "16th", "energetic"),
    ("cumbia", "verse", 0.70, 100, "A minor",
     "Cumbia-Groove mit Maracas-artigem HiHat",
     [0.0, 1.5, 2.0, 3.5], [1.0, 3.0], "8th", "festive"),
    ("uk garage", "chorus", 0.80, 130, "C minor",
     "2-Step UK-Garage-Rhythmus mit Synkope",
     [0.0, 1.75, 2.5], [1.0, 3.0], "offbeat", "energetic"),
]

INSTRUMENT_SPECS_EXT: list = [
    ("pad", "ambient", "melancholic", 0.30, [
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 48, 84, 0.45,
         "Sanfter atmosphärischer Pad — ideal für Ambient-Texturen", 0.93),
        ("Phase-4", "f4d2a1b0-0001-4000-8000-000000000002", 48, 84, 0.42,
         "Phase-Distortion-Pad, etwas bewegter", 0.72),
    ]),
    ("pad", "techno", "driving", 0.80, [
        ("Phase-4", "f4d2a1b0-0001-4000-8000-000000000002", 55, 84, 0.72,
         "Harter, modulierter Techno-Pad mit Bewegung", 0.88),
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 55, 84, 0.68,
         "Subtraktiver Synth-Pad, breiter", 0.74),
    ]),
    ("arp", "house", "uplifting", 0.75, [
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 60, 96, 0.75,
         "Heller, pulsierender House-Arpeggiator — klassisch", 0.91),
        ("Phase-4", "f4d2a1b0-0001-4000-8000-000000000002", 60, 96, 0.72,
         "Phase-Arp, leicht metallisch", 0.70),
    ]),
    ("arp", "trance", "uplifting", 0.85, [
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 60, 96, 0.80,
         "Supersaw-Arpeggio — Trance-typisch und euphorisch", 0.93),
        ("Phase-4", "f4d2a1b0-0001-4000-8000-000000000002", 60, 96, 0.75,
         "Phase-Arp, alternativ", 0.71),
    ]),
    ("chords", "pop", "bright", 0.65, [
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 48, 84, 0.65,
         "Klarer, heller Pop-Synth-Chord-Stack", 0.87),
        ("Phase-4", "f4d2a1b0-0001-4000-8000-000000000002", 48, 84, 0.60,
         "Phase-4-Chords, etwas dunkler", 0.70),
    ]),
    ("lead", "blues", "soulful", 0.70, [
        ("FM-4", "f4d2a1b0-0001-4000-8000-000000000001", 55, 91, 0.75,
         "Expressiver Blues-Lead mit FM-Overdriven-Charakter", 0.89),
        ("Polymer", "f4d2a1b0-0001-4000-8000-000000000003", 55, 91, 0.70,
         "Subtraktiver Lead, weniger gebogen", 0.68),
    ]),
]


def _instrument_pair(spec) -> dict:
    role, genre, mood, energy, options = spec

    kb_options = [
        {
            "device_name": d, "uuid": u, "midi_range": [lo, hi],
            "default_velocity": dv, "description": desc, "score": sc,
        }
        for (d, u, lo, hi, dv, desc, sc) in options
    ]
    tool_result = {role: kb_options}

    user = (
        "Kontext:\n"
        f"Instrument-KB für {genre}, Rolle={role}, Mood={mood}, Energie={energy}:\n"
        f"→ {json.dumps(tool_result, ensure_ascii=False)}\n\n"
        f"Wähle das passende Instrument für die {role.capitalize()}-Spur in einem "
        f"{genre}-Song. Nutze die KB-Empfehlung, kein hardcodiertes Device."
    )

    top = options[0]
    second = options[1]
    think = (
        "<think>\n"
        f"[Rolle: {role}] [Genre: {genre}] [Mood: {mood}] [Energie: {energy}]\n"
        f"1. KB-Ranking:\n"
        f"   - {top[0]} (Score {top[6]}) — {top[5]}\n"
        f"   - {second[0]} (Score {second[6]}) — {second[5]}\n"
        f"2. Entscheidung: {top[0]} → höchster KB-Score, genre-passend.\n"
        f"3. MIDI-Range {top[2]}–{top[3]}, default_velocity {top[4]}.\n"
        f"4. Fallback nur wenn KB leer: {second[0]}. Hier nicht nötig.\n"
        f"5. Korrekter Workflow: execute_setup mit load_instrument-Step (kein direkter load_instrument-Call).\n"
        "</think>"
    )

    # execute_setup ist das korrekte Tool — load_instrument ist nur ein Step-Typ darin.
    tool_call = {
        "tool": "execute_setup",
        "args": {
            "result": {
                "context_type": "song",
                "target": {"role": role, "genre": genre},
                "steps": [
                    {"type": "add_track", "args": {}},
                    {"type": "load_instrument", "args": {"name": top[0], "uuid": top[1]}},
                ],
            }
        },
    }
    assistant = f"{think}\n{json.dumps(tool_call, ensure_ascii=False)}"

    return {"messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]}


# ---------------------------------------------------------------------------
# Section-variant augmentation — deterministic, no LLM calls
# ---------------------------------------------------------------------------

# For each base section, derive additional section variants by shifting energy.
# Format: base_section -> [(new_section, energy_delta, description_suffix)]
_SECTION_DERIVE: dict[str, list[tuple[str, float, str]]] = {
    "verse":  [("chorus", +0.18, "— gesteigerte Energie im Chorus")],
    "chorus": [("verse",  -0.18, "— reduzierte Energie im Verse"),
               ("break",  +0.10, "— maximale Energie im Break")],
    "drop":   [("verse",  -0.40, "— aufbauender Intro/Verse")],
}


def _derive_section_variants(base_specs: list) -> list:
    """Generate section variants from base specs by adjusting section label and energy.

    Kick/snare/hat structure is kept identical — ``_energy_scale()`` in
    ``_build_drum_notes()`` already produces the velocity difference from the
    changed energy value, so the model learns the section→energy→velocity mapping
    without requiring hand-crafted per-section note lists.
    """
    variants = []
    for spec in base_specs:
        genre, section, energy, bpm, key, desc, kick_b, snare_b, hat, mood = spec
        for new_section, delta, suffix in _SECTION_DERIVE.get(section, []):
            new_energy = round(max(0.25, min(0.98, energy + delta)), 2)
            variants.append((
                genre, new_section, new_energy, bpm, key,
                f"{desc} {suffix}",
                kick_b, snare_b, hat, mood,
            ))
    return variants


def _all_rhythm_specs() -> list:
    base = RHYTHM_SPECS + RHYTHM_SPECS_EXT
    return base + _derive_section_variants(base)


def _all_instrument_specs() -> list:
    return INSTRUMENT_SPECS + INSTRUMENT_SPECS_EXT


# ---------------------------------------------------------------------------
# Build + validate + write
# ---------------------------------------------------------------------------

def build_pairs() -> list[dict]:
    pairs = [_rhythm_pair(s) for s in _all_rhythm_specs()]
    pairs += [_instrument_pair(s) for s in _all_instrument_specs()]
    for p in pairs:
        _validate_pair(p)
    return pairs


def _validate_pair(pair: dict) -> None:
    msgs = pair["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"], "Rollen-Reihenfolge"
    assert msgs[0]["content"] == SYSTEM_PROMPT, "System-Prompt muss Version 4 sein"
    assistant = msgs[-1]["content"]
    # Closed-think Invariante (Qwen3 </think>-Problem)
    assert assistant.count("<think>") == 1, "genau ein <think>"
    assert assistant.count("</think>") == 1, "</think> muss geschlossen sein"
    assert assistant.index("<think>") < assistant.index("</think>"), "</think> nach <think>"
    # Tool-Call ist valides JSON
    tool_json = assistant.split("</think>", 1)[1].strip()
    obj = json.loads(tool_json)
    assert obj.get("tool") in {"write_pattern", "execute_setup"}, \
        f"bekanntes Tool (got: {obj.get('tool')})"
    # Finite Drum-Notes bei write_pattern
    if obj["tool"] == "write_pattern":
        notes = json.loads(obj["args"]["notes"])
        assert notes, "nicht-leeres Pattern"
        for n in notes:
            assert 0 <= n["step"] <= 15, f"Step im Takt: {n['step']}"
            assert n["duration"] >= 1, "Note hat Länge"
        assert len(notes) <= 24, "Pattern gecappt (kein Runaway)"
    # execute_setup hat steps-Liste
    elif obj["tool"] == "execute_setup":
        result = obj["args"].get("result", {})
        assert "steps" in result, "execute_setup result braucht steps"
        assert len(result["steps"]) >= 1, "mindestens ein Step"


def _existing_user_messages() -> set[str]:
    seen: set[str] = set()
    if not TRAIN_FILE.exists():
        return seen
    with TRAIN_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            for m in d.get("messages", []):
                if m.get("role") == "user":
                    seen.add(m["content"])
    return seen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="nur validieren, nicht schreiben")
    ap.add_argument("--print", type=int, default=0, metavar="N", help="erste N Pairs zeigen")
    args = ap.parse_args()

    pairs = build_pairs()
    n_base_r  = len(RHYTHM_SPECS) + len(RHYTHM_SPECS_EXT)
    n_derived = len(_derive_section_variants(RHYTHM_SPECS + RHYTHM_SPECS_EXT))
    n_instr   = len(INSTRUMENT_SPECS) + len(INSTRUMENT_SPECS_EXT)
    print(f"✓ {len(pairs)} Pairs gebaut & validiert "
          f"({n_base_r} Rhythm-Basis, +{n_derived} Abgeleitet, "
          f"{n_instr} Instrument), "
          "alle <think> geschlossen, Drums finit.")

    if args.print:
        for p in pairs[: args.print]:
            print("-" * 70)
            for m in p["messages"]:
                print(f"[{m['role'].upper()}]\n{m['content']}\n")

    existing = _existing_user_messages()
    new_pairs = [p for p in pairs
                 if p["messages"][1]["content"] not in existing]
    dupes = len(pairs) - len(new_pairs)

    if args.dry_run:
        print(f"[dry-run] {len(new_pairs)} neu, {dupes} bereits vorhanden — nichts geschrieben.")
        return

    if not new_pairs:
        print(f"Nichts anzuhängen — alle {len(pairs)} Pairs bereits in {TRAIN_FILE.name}.")
        return

    with TRAIN_FILE.open("a") as f:
        for p in new_pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"✓ {len(new_pairs)} neue Pairs an {TRAIN_FILE} angehängt "
          f"({dupes} Duplikate übersprungen).")


if __name__ == "__main__":
    main()
