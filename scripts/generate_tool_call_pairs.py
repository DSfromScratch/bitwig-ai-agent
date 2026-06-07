#!/usr/bin/env python3
"""
Generiert Tool-Call-Trainingspairs im OpenAI-Format.

Problem: Alle bisherigen Trainingsdaten (2727 Paare) hatten 0 tool_calls.
Das Modell hat nie gelernt, bei Nutzer-Anfragen zuerst ein Tool aufzurufen —
es antwortet direkt aus dem Trainings-Wissen statt query_bitwig_docs zu rufen.

Korrekter Workflow (nach Nutzer-Feedback):
  Phase 1 — Wissen sammeln:
    query_bitwig_docs → [Lücke?] → web_search + find_audio_example
  Phase 2 — Notenplan (BEVOR Bitwig berührt wird):
    Tonart, BPM, Akkordfolge, Drum-Pattern intern festlegen
  Phase 3 — Bitwig steuern:
    check_connection → execute_setup → write_pattern (pro Track) → Tipps

  WICHTIG: Künstler- und Song-Anfragen → web_search ZUERST (kein query_bitwig_docs)
    Die KB kennt nur Bitwig-Devices, Genres, Workflows — keine Künstler oder Songs.

Typen:
  1. Informational     — Genre-Fragen → query_bitwig_docs → Erklärung
  2. Device-Query      — "Welche Devices für X?" → query → Gerät-Liste
  3. Workflow          — "Wie erstelle ich X?" → query → Schritt-für-Schritt
  4. Gap-Detection     — query liefert Lücken → web_search + find_audio_example → Notenplan
  5. Full-Production   — komplette Kette: query→web→plan→check→setup→write→tipps
  6. Artist            — Künstler-Stil → web_search DIREKT (KB hat keine Künstlerdaten)
  7. Song              — Song nachbauen → web_search + find_audio_example DIREKT → Notenplan
  8. No-Tool           — Fragen die KEIN Tool brauchen

Format: OpenAI tool_calls (nicht Qwen-XML, nicht JSON-Text im Content)
Output: data/training/tool_call_pairs.jsonl
"""
from __future__ import annotations

import json
import random
import uuid
from pathlib import Path

random.seed(42)

# ── System-Prompt (identisch zur Produktionsumgebung) ─────────────────────────

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

# ── Genre-Datenbank mit simulierten Neo4j-Ergebnissen ─────────────────────────

GENRES: dict[str, dict] = {
    "Brostep": {
        "bpm": "140–150",
        "key": "D minor",
        "characteristics": "Aggressiver Dubstep-Subgenre, tiefe modulierende Bässe (Wobble), schwere Drops, Snare auf 3, synkopierte Rhythmen, verzerrte Reese-Basslines.",
        "devices": ["FM-4 (Wobble-Bass, Algo 2)", "Phase-4 (Lead-Synth)", "VD-Heavy Kick", "VD-Snare", "Ladder-Filter", "Saturator", "Delay-2", "Reverb"],
        "neo4j_result": (
            "Genre: Brostep\n"
            "BPM: 140–150 | Tonart: D minor | Energie: hoch\n"
            "Empfohlene Devices:\n"
            "  - FM-4 (Wobble-Bass): Algorithm 2, Feedback 0.3, LFO auf Cutoff → Wobble-Effekt\n"
            "  - Phase-4 (Lead): Saw-Wave, Detune 0.2, Chorus\n"
            "  - VD-Heavy Kick (MIDI 36), VD-Snare (MIDI 38)\n"
            "  - Ladder-Filter (Cutoff 800 Hz, Resonance 0.6) nach FM-4\n"
            "  - Saturator (Drive 0.4) für Grit\n"
            "Drum-Pattern (16 Steps): Kick [0,8], Snare [4,12], Open-HH [2,6,10,14]\n"
            "Bassline: D2–F2–G2–A2, lange Noten (4 Beats), LFO-Wobble\n"
            "Workflow: FM-4 Bass → Ladder-Filter → Saturator → Reverb (Dry/Wet 20%)"
        ),
    },
    "Neurofunk": {
        "bpm": "172–180",
        "key": "G minor",
        "characteristics": "Komplexe Breakbeat-Muster, modulierende FM-Reese-Basslines, technisch, dunkel, industriell.",
        "devices": ["FM-4 (Reese-Bass)", "VD-Heavy Kick", "Compressor", "EQ-5", "Saturator"],
        "neo4j_result": (
            "Genre: Neurofunk\n"
            "BPM: 172–180 | Tonart: G minor | Energie: sehr hoch\n"
            "Empfohlene Devices:\n"
            "  - FM-4 (Reese-Bass): Algorithm 1, zwei Ops im Unisono, detuned ±5 Cent\n"
            "  - VD-Heavy Kick (MIDI 36), komplexes Breakbeat-Snare-Pattern\n"
            "  - EQ-5: Boost bei 80 Hz (+6 dB), Cut bei 300 Hz (−4 dB)\n"
            "  - Compressor: Ratio 4:1, Attack 10ms, Release 80ms\n"
            "Drum-Pattern: Kick [0,3,7,9,13], Snare [4,11,14] — unregelmäßig\n"
            "Bassline: G1–G2–D2–A#1, rollende 16tel, starke Modulation"
        ),
    },
    "Deep House": {
        "bpm": "120–126",
        "key": "F minor",
        "characteristics": "Warme Bassline, subtiler 4-on-the-floor Kick, jazzy Akkorde, Piano-Chords, atmosphärische Vocals, soulful.",
        "devices": ["Polysynth (Piano-Chords)", "Phase-4 (Pad)", "FM-4 (Bass)", "Reverb", "Delay-2", "Compressor"],
        "neo4j_result": (
            "Genre: Deep House\n"
            "BPM: 120–126 | Tonart: F minor | Energie: mittel\n"
            "Empfohlene Devices:\n"
            "  - Polysynth (Piano-Chords): Saw+Sub, Cutoff 1200 Hz, leichter Chorus\n"
            "  - FM-4 (Bass): warme Sinuswelle, Sustain lang, leichter Overdrive\n"
            "  - Phase-4 (Pad): langsame Attack (500ms), Reverb (Decay 4s)\n"
            "  - Delay-2 (1/8 Ping-Pong, Feedback 35%)\n"
            "Drum-Pattern: 4-on-floor Kick [0,4,8,12], Clap [4,12], 16tel HH\n"
            "Bassline: F2–C2–D#2–A#1, Off-Beat (Step 2,6,10,14)"
        ),
    },
    "Dark Techno": {
        "bpm": "130–140",
        "key": "D minor",
        "characteristics": "Schwerer verzerrter Kick (4-on-the-floor), industrielle Atmosphäre, Moll-Tonarten, treibende Bassline, Berlin-Stil.",
        "devices": ["FM-4 (Bass)", "Saturator", "Ladder-Filter", "EQ-5", "Reverb"],
        "neo4j_result": (
            "Genre: Dark Techno\n"
            "BPM: 130–140 | Tonart: D minor | Energie: hoch\n"
            "Empfohlene Devices:\n"
            "  - FM-4 (Bassline): treibend, kurze Attack, Overdrive +40%\n"
            "  - Saturator auf Kick (Drive 0.6, Tone −0.2)\n"
            "  - Ladder-Filter (Cutoff 600 Hz, Resonance 0.5)\n"
            "  - Reverb (Hall, Decay 3s, Dry/Wet 25%) auf Snare\n"
            "Drum-Pattern: Kick [0,4,8,12], Snare [4,12], Hat [2,10] — minimal\n"
            "Bassline: D2–A1–G1–F1, jede Note 2 Beats, stark komprimiert"
        ),
    },
    "Lo-fi Hip Hop": {
        "bpm": "75–90",
        "key": "C major",
        "characteristics": "Geschwungener Boom-Bap-Beat, warme Vinyl-Textur, Jazz-Akkorde, entspannte Atmosphäre.",
        "devices": ["Polysynth (Jazz-Chords)", "Sampler (Vinyl)", "FM-4 (Bass)", "Reverb", "Delay-2"],
        "neo4j_result": (
            "Genre: Lo-fi Hip Hop\n"
            "BPM: 75–90 | Tonart: C major / A minor | Energie: niedrig\n"
            "Empfohlene Devices:\n"
            "  - Polysynth: Jazzy Maj7/min7-Akkorde, langsame Attack\n"
            "  - Sampler: Vinyl-Crackle-Sample als Textur-Layer\n"
            "  - FM-4 (Bass): warm, sinusförmig, wenig Oberton\n"
            "  - Reverb (Room, Decay 2s), leichter Delay (1/4)\n"
            "Drum-Pattern: Kick [0,10] (Boom-Bap), Snare [4,12], HH [0,3,6,9,12,15]\n"
            "Akkord-Progression: Cmaj7–Am7–Fmaj7–G7 (4 Takte)"
        ),
    },
    "Trap": {
        "bpm": "130–150",
        "key": "A minor",
        "characteristics": "Schwerer 808-Bass, Snare auf 2+4, 16tel und 32tel Hi-Hat-Rolls, Atlanta-Stil.",
        "devices": ["FM-4 (808-Bass)", "Phase-4 (Melody)", "VD-Heavy Kick", "VD-Snare"],
        "neo4j_result": (
            "Genre: Trap\n"
            "BPM: 130–150 | Tonart: A minor | Energie: hoch\n"
            "Empfohlene Devices:\n"
            "  - FM-4 (808-Bass): langer Sustain (8–16 Beats), Pitchbend-Slides\n"
            "  - Phase-4 (Bell/Melody): kurze Decay, hohe Oktave\n"
            "  - VD-Heavy Kick (MIDI 36), VD-Snare (MIDI 38)\n"
            "Drum-Pattern: Kick [0,6,10], Snare [4,12], Hi-Hat 32tel-Rolls [0..15]\n"
            "808-Bass: A1 (langer Note, Slide zu E1), jede 2–3 Takte"
        ),
    },
    "House": {
        "bpm": "120–130",
        "key": "C minor",
        "characteristics": "4-on-the-Floor Kick, Clap/Snare auf 2+4, soulful Akkorde, Off-Beat-Bassline.",
        "devices": ["Polysynth (Akkorde)", "FM-4 (Bass)", "VD-Kick", "VD-Snare", "Reverb", "Delay-2"],
        "neo4j_result": (
            "Genre: House\n"
            "BPM: 120–130 | Tonart: C minor | Energie: mittel-hoch\n"
            "Empfohlene Devices:\n"
            "  - Polysynth (Akkorde): Stab-Chords (Cm7, Fm7), kurze Attack\n"
            "  - FM-4 (Bass): Off-Beat, Step 2+10, warm und rund\n"
            "  - 4-on-floor: Kick [0,4,8,12], Clap [4,12]\n"
            "  - Reverb (Decay 2s) + Delay (1/8 Sync)\n"
            "Bassline: C2–G2–A#1–G1, Offbeat-Timing (Swing 55%)"
        ),
    },
    "Ambient": {
        "bpm": "60–90",
        "key": "C major",
        "characteristics": "Lange Pad-Flächen, keine oder sehr sparsame Percussion, atmosphärische Texturen, langsame Akkordwechsel.",
        "devices": ["Phase-4 (Pad)", "Polymer (Textur)", "Reverb", "Delay-2", "EQ-5"],
        "neo4j_result": (
            "Genre: Ambient\n"
            "BPM: 60–90 (oder kein Tempo) | Tonart: C major | Energie: sehr niedrig\n"
            "Empfohlene Devices:\n"
            "  - Phase-4 (Pad): sehr langer Attack (2s), Decay 8s, Reverb Pre-Send\n"
            "  - Polymer (Granular-Textur): Grain-Size 200ms, Spray 0.8\n"
            "  - Reverb (Hall, Decay 12s, Dry/Wet 70%)\n"
            "  - EQ-5: Cut unter 80 Hz, Cut über 8 kHz\n"
            "Keine Drums. Akkordwechsel alle 8–16 Takte."
        ),
    },
    "Drum and Bass": {
        "bpm": "170–180",
        "key": "D minor",
        "characteristics": "Breakbeat (Kick+Snare synkopiert), rollende 16tel-Bassline, tiefer Sub-Bass, energetisch.",
        "devices": ["FM-4 (Sub-Bass)", "Phase-4 (Reese)", "VD-Kick", "VD-Snare", "Compressor", "EQ-5"],
        "neo4j_result": (
            "Genre: Drum and Bass\n"
            "BPM: 170–180 | Tonart: D minor | Energie: sehr hoch\n"
            "Empfohlene Devices:\n"
            "  - FM-4 (Sub-Bass): tiefer Sinus (D1), langer Sustain\n"
            "  - Phase-4 (Reese-Bass): Detuned Saw x2, Filter-Automation\n"
            "  - Compressor auf Sub-Bass (Sidechain vom Kick)\n"
            "  - EQ-5: Sub-Boost 60 Hz (+4 dB), Mid-Cut 300 Hz\n"
            "Drum-Pattern (Breakbeat): Kick [0,5,8,13], Snare [4,12,14]\n"
            "Bassline: D1–A1–F1–C2, rollende 16tel"
        ),
    },
    "Minimal Techno": {
        "bpm": "124–130",
        "key": "C minor",
        "characteristics": "Sehr sparsame Elemente, 4-on-floor Kick, subtile Details, Hypnotik durch Wiederholung.",
        "devices": ["FM-4 (Bass)", "Ladder-Filter", "Compressor", "Delay-2"],
        "neo4j_result": (
            "Genre: Minimal Techno\n"
            "BPM: 124–130 | Tonart: C minor | Energie: mittel\n"
            "Empfohlene Devices:\n"
            "  - FM-4 (Bass): sehr subtil, kurze Noten, minimale Modulation\n"
            "  - Ladder-Filter mit langsamer LFO-Automation (16 Takte)\n"
            "  - Compressor (Glue, Ratio 2:1)\n"
            "  - Delay-2 (1/8, Feedback 20%) für Rhythmik\n"
            "Drum-Pattern: Kick [0,4,8,12], Snare [8] nur, HH [2,10] sehr subtil\n"
            "Bassline: C2 gehalten, gelegentlich G1 — Hypnotik durch Wiederholung"
        ),
    },
    "Reggaeton": {
        "bpm": "90–100",
        "key": "G minor",
        "characteristics": "Dembow-Rhythmus (Kick+Snare auf 3), lateinamerikanisch, tanzbar, Off-Beat-Percussion.",
        "devices": ["Polysynth (Hookline)", "FM-4 (Bass)", "VD-Kick", "VD-Snare", "Reverb"],
        "neo4j_result": (
            "Genre: Reggaeton\n"
            "BPM: 90–100 | Tonart: G minor | Energie: hoch\n"
            "Empfohlene Devices:\n"
            "  - Dembow-Rhythmus: Kick [0,4,8,12], Snare [3,8,12] — charakteristischer Off-Beat\n"
            "  - FM-4 (Bass): tief, warm, kurze Noten auf Off-Beat\n"
            "  - Polysynth (Hook): kurze synkopierte Melodie-Phrase\n"
            "  - Reverb (Room, kurz) auf Snare\n"
            "Bassline: G2–D2–A#1–F2, eine Note pro Takt, lang ausgehalten"
        ),
    },
    "Afrobeats": {
        "bpm": "95–105",
        "key": "F major",
        "characteristics": "Westafrikanische Rhythmen, polyrhythmische Percussion, tanzbar, Dur-Tonarten, lebhaft.",
        "devices": ["Polysynth (Akkorde)", "FM-4 (Bass)", "Sampler (Percussion)", "Reverb"],
        "neo4j_result": (
            "Genre: Afrobeats\n"
            "BPM: 95–105 | Tonart: F major | Energie: hoch\n"
            "Empfohlene Devices:\n"
            "  - Polysynth: Maj7-Akkorde (Fmaj7, Gm7, Am7, Bb maj7)\n"
            "  - FM-4 (Bass): warm, Offbeat (Step 2+10), Slide zwischen Noten\n"
            "  - Sampler: Afro-Percussion (Congas, Shakers, Talking Drum)\n"
            "  - Reverb (Room, Decay 1.5s)\n"
            "Drum-Pattern: Kick [0,3,8,11], Snare [4,12], Shaker [0..15] durchgehend\n"
            "Akkord-Progression: Fmaj7–Gm7–Am7–Bbmaj7 (Dur-basiert, lebhaft)"
        ),
    },
    "Jazz": {
        "bpm": "120–160",
        "key": "Bb major",
        "characteristics": "Swing-Feel, komplexe Akkorde (Maj7, Min7, Dom7, Dim7), Walking Bass, Ride-Cymbal statt HiHat, Offbeat-Snare.",
        "devices": ["Polysynth (Piano)", "FM-4 (Bass)", "Sampler (Ride MIDI 51)", "Reverb"],
        "neo4j_result": (
            "Genre: Jazz\n"
            "BPM: 120–160 | Tonart: Bb major | Energie: mittel\n"
            "Empfohlene Devices:\n"
            "  - Polysynth (Piano): Bbmaj7–Cm7–Dm7–Ebmaj7, Voicing in Oktave 3–4\n"
            "  - FM-4 (Walking Bass): chromatische Passing-Tones, jede Note 1 Beat\n"
            "  - Ride-Cymbal: MIDI 51, durchgehend auf jedem Beat (Swing!)\n"
            "  - Snare: MIDI 38, nur auf Beat 2+4 (Offbeat)\n"
            "  - Reverb (Hall, Decay 3s)\n"
            "Drum-Pattern (Swing): Ride [0,2,4,6,8,10,12,14], Snare [4,12]\n"
            "Walking Bass: Bb2–C2–D2–Eb2 (chromatisch, Swing-Timing)"
        ),
    },
    "UK Garage": {
        "bpm": "130–135",
        "key": "C minor",
        "characteristics": "Synkopierter 2-Step-Beat (nicht 4-on-floor), Swing, Off-Beat-Bassline, kurze Vocal-Chops.",
        "devices": ["Polysynth (Chords)", "FM-4 (Bass)", "VD-Kick", "VD-Snare", "Delay-2"],
        "neo4j_result": (
            "Genre: UK Garage\n"
            "BPM: 130–135 | Tonart: C minor | Energie: mittel-hoch\n"
            "Empfohlene Devices:\n"
            "  - 2-Step Beat: Kick [0,3,10], Snare [4,14] — synkopiert, Swing 60%\n"
            "  - FM-4 (Bass): Off-Beat, kurze Noten, stark komprimiert\n"
            "  - Polysynth: kurze Chord-Stabs (Swing-timing)\n"
            "  - Delay-2 (Ping-Pong 1/8, Feedback 30%)\n"
            "Bassline: C2–G1–A#1–G1, Off-Beat auf Step 3,8,11"
        ),
    },
    "Dubstep": {
        "bpm": "138–142",
        "key": "E minor",
        "characteristics": "Halbzeit-Groove, Wobble-Bass, schwere Drops, Snare auf Step 3 (Beat 2 im Halbzeit-Gefühl).",
        "devices": ["FM-4 (Wobble-Bass)", "Phase-4 (Lead)", "Ladder-Filter", "Saturator", "Reverb"],
        "neo4j_result": (
            "Genre: Dubstep\n"
            "BPM: 138–142 | Tonart: E minor | Energie: hoch\n"
            "Empfohlene Devices:\n"
            "  - FM-4 (Wobble-Bass): Algorithm 2, LFO auf Cutoff (Rate: 1/4)\n"
            "  - Phase-4 (Lead): aggressive Saw-Wave, Glide 50ms\n"
            "  - Ladder-Filter (Key-tracking, Resonance 0.7)\n"
            "  - Saturator (Drive 0.5) + Reverb (Decay 3s)\n"
            "Drum-Pattern (Halbzeit): Kick [0,12], Snare [8] — langsam und schwer\n"
            "Wobble-Bass: E1 gehalten, Cutoff-LFO erzeugt Wobble-Rhythmus"
        ),
    },
}

# Genres mit absichtlich lückenhaftem KB-Ergebnis (triggert web_search)
GENRES_WITH_GAPS: dict[str, dict] = {
    "Brostep": {
        "bpm": "140–150", "key": "D minor",
        "devices": ["FM-4 (Wobble-Bass)", "Ladder-Filter", "VD-Heavy Kick", "VD-Snare", "Saturator"],
        "neo4j_result_partial": (
            "Genre: Brostep\n"
            "BPM: 140–150 | Energie: hoch\n"
            "Hinweis: Subgenre von Dubstep — aggressiver, härtere Drops.\n"
            "Empfohlene Devices: FM-4, Ladder-Filter\n"
            "LÜCKE: Keine Akkordfolge, kein Drum-Pattern in der KB."
        ),
        "web_result": (
            "web_search('Brostep typical bass pattern chord progression BPM'):\n"
            "→ Brostep: 140–150 BPM, D minor typisch\n"
            "→ Wobble-Bass: D2 gehalten, LFO Rate 1/4, Cutoff 200–800 Hz\n"
            "→ Drum-Pattern: Kick [0,8], Snare [4,12], Open-HH [2,6,10,14]\n"
            "→ Drop-Energie 100%: alle Elemente gleichzeitig, starker Sidechain Kick→Bass"
        ),
        "audio_result": (
            "find_audio_example('brostep drop drum loop 140 BPM'):\n"
            "→ BPM: 145 | Tonart: D minor | Energie: 0.98\n"
            "→ Onset-Steps: [0, 4, 8, 12] (Kick) + [4, 12] (Snare)\n"
            "→ Takt 1: X...X...X...X..."
        ),
        "note_plan": (
            "Notenplan Brostep (D minor, 145 BPM):\n"
            "  Drum-Track (VD-Heavy Kick): Kick D2=36 [s0,s8], Snare=38 [s4,s12], Open-HH=46 [s2,s6,s10,s14]\n"
            "  Bass-Track (FM-4 Wobble): D2=38 gehalten (16 Steps), LFO auf Cutoff\n"
            "  Lead-Track (Phase-4): D4→F4→G4→A4, je 2 Steps, nach Drop"
        ),
    },
    "Kuduro": {
        "bpm": "140–155", "key": "A minor",
        "devices": ["FM-4 (Bass)", "VD-Heavy Kick", "Sampler (Perc)"],
        "neo4j_result_partial": (
            "Genre: Kuduro\n"
            "BPM: 140–155 | Ursprung: Angola (Luanda)\n"
            "Empfohlene Devices: FM-4, Percussion-Sampler\n"
            "LÜCKE: Kein Drum-Pattern, keine typische Akkordfolge in der KB."
        ),
        "web_result": (
            "web_search('Kuduro drum pattern rhythm Angola typical BPM'):\n"
            "→ Kuduro: 140–155 BPM, stark synkopierte Kicks (NICHT 4-on-floor)\n"
            "→ Typisches Pattern: Kick [0,3,7,12], Snare [4,14], sehr aggressiv\n"
            "→ Bassline: kurze Noten, Off-Beat, A minor"
        ),
        "audio_result": (
            "find_audio_example('kuduro drum loop Angola 145 BPM syncopated'):\n"
            "→ BPM: 148 | Tonart: A minor | Energie: 1.0\n"
            "→ Onset-Steps: [0, 3, 7, 12] (stark synkopiert, charakteristisch)\n"
            "→ Takt 1: X..X...X...X..."
        ),
        "note_plan": (
            "Notenplan Kuduro (A minor, 148 BPM):\n"
            "  Drum-Track: Kick=36 [s0,s3,s7,s12], Snare=38 [s4,s14], Clap=39 [s8]\n"
            "  Bass-Track (FM-4): A2=45 [s0,dur2], E2=40 [s3,dur2], kurz und percussiv\n"
            "  Perc-Track: Shaker=42 [s0..s15] durchgehend, vel=0.4"
        ),
    },
    "Singeli": {
        "bpm": "180–220", "key": "C minor",
        "devices": ["FM-4 (Bass)", "Phase-4 (Synth)", "Sampler (Perc)"],
        "neo4j_result_partial": (
            "Genre: Singeli\n"
            "LÜCKE: Wenig Daten in der KB. Tansanisches Dance-Genre, sehr hohes BPM."
        ),
        "web_result": (
            "web_search('Singeli music Tanzania BPM drum pattern characteristics'):\n"
            "→ Singeli: 180–220 BPM (!) — extrem schnell, Dar-es-Salaam Ursprung\n"
            "→ Kick auf JEDEM 16tel-Step ([0..15]), kein Swing\n"
            "→ Hochenergetische Percussion, einfache repetitive Bassline\n"
            "→ C minor oder G minor typisch"
        ),
        "audio_result": (
            "find_audio_example('singeli drum loop Tanzania 200 BPM'):\n"
            "→ BPM: 200 | Tonart: C minor | Energie: 1.0\n"
            "→ Onset-Steps: [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15] (alle 16tel!)\n"
            "→ Takt 1: XXXXXXXXXXXXXXXX"
        ),
        "note_plan": (
            "Notenplan Singeli (C minor, 200 BPM):\n"
            "  Drum-Track: Kick=36 alle 16tel [s0..s15], vel=0.9\n"
            "  Bass-Track (FM-4): C2=36 [s0,dur4], G1=31 [s8,dur4] — simpel, repetitiv\n"
            "  Synth-Track (Phase-4): C4 [s0,dur2], G4 [s4,dur2] — sparse melody"
        ),
    },
}

# ── Künstler-Datenbank (web_search direkt — KB hat keine Künstlerdaten) ────────

ARTISTS: dict[str, dict] = {
    "Aphex Twin": {
        "genre": "IDM / Ambient Techno",
        "bpm": "120–160",
        "key": "A minor",
        "style": "Experimentell, glitchig, komplexe Polyrhythmen, verzerrte Acid-Basslines, unkonventionelle Taktarten.",
        "devices": ["FM-4 (Acid-Bass)", "Phase-4 (Glitch-Lead)", "Polymer (Textur)", "Ladder-Filter", "Saturator", "Delay-2"],
        "web_result": (
            "web_search('Aphex Twin production style techniques IDM'):\n"
            "→ BPM: 120–160 (oft unregelmäßig, auch 54 BPM für Ambient)\n"
            "→ Signatur: Roland TB-303 Acid-Basslines, Roland 909 Drums verzerrt\n"
            "→ Polyrhythmen: Kick in 5/4, Snare in 7/8 gleichzeitig möglich\n"
            "→ Processing: starkes Bitcrushing, granulare Resynthese, Reverb (sehr lang)\n"
            "→ Tonart: häufig Moll (A minor, D minor), manchmal atonal\n"
            "→ Key Devices: Analog-Synths (Minimoog, Buchla), Selbstbau-Hardware"
        ),
        "audio_result": (
            "find_audio_example('Aphex Twin Come To Daddy drum pattern IDM 160 BPM'):\n"
            "→ BPM: 155 | Tonart: A minor | Energie: 0.95\n"
            "→ Kick-Onset: [0,2,5,9,12] — unregelmäßig, kein Standard-4-on-floor\n"
            "→ Snare: [4,7,14] — synkopiert\n"
            "→ Acid-Bass: A2 Slide→E2→G2, scharfer Filter-Sweep"
        ),
        "note_plan": (
            "Notenplan Aphex-Twin-Stil (A minor, 155 BPM):\n"
            "  Drum-Track: Kick=36 [s0,s2,s5,s9,s12], Snare=38 [s4,s7,s14] — unregelmäßig!\n"
            "  Acid-Bass (FM-4): A2=45 [s0,dur3,Slide], E2=40 [s4,dur2], G2=43 [s8,dur2]\n"
            "    → Ladder-Filter: Cutoff-Automation 200→2000Hz über 16 Steps\n"
            "  Textur (Polymer): A2 gehalten, Grain-Size 50ms, Spray 0.9 — für Glitch-Textur"
        ),
    },
    "Burial": {
        "genre": "UK Garage / Dark Ambient",
        "bpm": "138–142",
        "key": "D minor",
        "style": "Gebrochene 2-Step-Beats, vinyl Crackle, detunte und gepitchte Vocal-Chops, dunkle Atmosphäre.",
        "devices": ["FM-4 (Sub-Bass)", "Sampler (Vocals/Vinyl)", "Phase-4 (Pad)", "Reverb", "Delay-2", "Compressor"],
        "web_result": (
            "web_search('Burial production style UK Garage dark ambient techniques'):\n"
            "→ BPM: 138–142 (UK Garage Half-Time-Feel)\n"
            "→ Signatur: Vinyl-Crackle-Loop als Textur, detunte Vocal-Samples (+/- 5–15 Cent)\n"
            "→ Drum-Pattern: stark gebrochener 2-Step (NICHT 4-on-floor)\n"
            "→ Kick: [0,10], Snare: [4,13] — sehr unregelmäßig\n"
            "→ Sub-Bass: tief, sinusförmig, sehr wenig Obertöne\n"
            "→ Atmosphäre: langer Hall (Decay 8–12s), Low-pass auf alles"
        ),
        "audio_result": (
            "find_audio_example('Burial Archangel drum beat 140 BPM 2-step'):\n"
            "→ BPM: 140 | Tonart: D minor | Energie: 0.55 (bewusst gedämpft)\n"
            "→ Kick: [0,10], Snare: [4,14] — 2-Step, nicht quantisiert\n"
            "→ Vinyl-Crackle kontinuierlich, vel=0.2–0.4 (zufällig)"
        ),
        "note_plan": (
            "Notenplan Burial-Stil (D minor, 140 BPM):\n"
            "  Drum-Track: Kick=36 [s0,s10], Snare=38 [s4,s14], HH=42 [s2,s6,s8,s12]\n"
            "    → KEIN Quantize, leichte Timing-Schwankungen\n"
            "  Sub-Bass (FM-4): D1=26 [s0,dur8], A1=33 [s8,dur4] — sehr tief, sinusförmig\n"
            "  Sampler: Vinyl-Crackle durchgehend [s0..s15], vel=0.25"
        ),
    },
    "Daft Punk": {
        "genre": "French House / Electro",
        "bpm": "120–128",
        "key": "F minor",
        "style": "Stark gefilterte Synths (French Filter-Sweep), Vocoder-Gesang, funky Basslines, 4-on-floor, Phaser-Effekte.",
        "devices": ["Phase-4 (Filter-Sweep)", "FM-4 (Funk-Bass)", "Polysynth (Akkorde)", "Ladder-Filter", "Reverb", "Delay-2"],
        "web_result": (
            "web_search('Daft Punk French House production style techniques filter sweep'):\n"
            "→ BPM: 120–128 (House-Tempo)\n"
            "→ Signatur: French Filter: Hochpass öffnet langsam über 8–16 Takte\n"
            "→ Vocoder auf Lead-Stimme (Roland VP-330 original)\n"
            "→ Funk-Bass: synkopiert, F minor Pentatonik, slides zwischen Noten\n"
            "→ Drum-Machine: Roland 909 (Kick), 808 (Snare) — Classic House Sound\n"
            "→ Chord-Stabs: Fm7 Staccato auf Off-Beats"
        ),
        "audio_result": (
            "find_audio_example('Daft Punk Around The World drum loop 121 BPM house'):\n"
            "→ BPM: 121 | Tonart: F minor | Energie: 0.85\n"
            "→ 4-on-floor Kick: [0,4,8,12], Snare: [4,12], HH: [2,6,10,14]\n"
            "→ Bass-Onset: [1,3,5,7,9,11,13,15] — jede 8tel, synkopiert"
        ),
        "note_plan": (
            "Notenplan Daft-Punk-Stil (F minor, 122 BPM):\n"
            "  Drums: 4-on-floor Kick=36 [s0,s4,s8,s12], Snare=38 [s4,s12], HH=42 [s2,s6,s10,s14]\n"
            "  Bass (FM-4): F2=41 [s1,dur1], C2=36 [s3,dur1], Db2=37 [s5,dur1] — Funk-Groove\n"
            "  Filter-Sweep: Phase-4 Pad auf Fm7, HPF-Cutoff von 2000→100Hz über 16 Takte"
        ),
    },
    "Skrillex": {
        "genre": "Brostep / Dubstep",
        "bpm": "140–150",
        "key": "E minor",
        "style": "Aggressive Wobble-Bässe, harte Drops, screechende Leads, Bitcrusher-Effekte, maximale Energie.",
        "devices": ["FM-4 (Wobble-Bass)", "Phase-4 (Screach-Lead)", "Ladder-Filter", "Saturator", "VD-Heavy Kick", "VD-Snare"],
        "web_result": (
            "web_search('Skrillex production style Brostep wobble bass techniques'):\n"
            "→ BPM: 140–150 (Half-Time-Feel im Drop)\n"
            "→ Signatur: 'Screach'-Lead — gesättigte Saw-Wave mit extremem Filter-Automation\n"
            "→ Wobble-Bass: FM-Synthese, LFO Rate 1/4 auf Cutoff, massive Overdrive\n"
            "→ Drop: alle Elemente gleichzeitig, Sidechain Kick→Bass sehr aggressiv\n"
            "→ Kick: verzerrter 909-Kick, transient-geshapet\n"
            "→ Tonart: E minor oder B minor typisch"
        ),
        "audio_result": (
            "find_audio_example('Skrillex Scary Monsters dubstep drop 145 BPM E minor'):\n"
            "→ BPM: 145 | Tonart: E minor | Energie: 1.0\n"
            "→ Kick (Half-Time): [0,12], Snare: [8] — Halbzeit-Pattern\n"
            "→ Wobble-Bass: E1=28 gehalten 16 Steps, Cutoff-LFO sehr tief"
        ),
        "note_plan": (
            "Notenplan Skrillex-Stil (E minor, 145 BPM):\n"
            "  Drums (Half-Time): Kick=36 [s0,s12], Snare=38 [s8] — bewusst sparse\n"
            "  Wobble-Bass (FM-4): E1=28 [s0,dur16] — eine Note gehalten, Cutoff-LFO macht Wobble\n"
            "    → Ladder-Filter: Cutoff 150Hz, Resonance 0.75, LFO 1/4-Rate\n"
            "  Screach-Lead (Phase-4): E4→G4→A4, nach Drop, extreme Sättigung"
        ),
    },
    "Four Tet": {
        "genre": "IDM / Deep House / Folktronica",
        "bpm": "118–126",
        "key": "C major",
        "style": "Organische Samples (Gitarre, Klavier), glitchige Percussion, warme Pad-Flächen, dezente Basslines.",
        "devices": ["Sampler (organische Samples)", "Polymer (Granular)", "Phase-4 (Pad)", "FM-4 (Bass)", "Reverb", "Delay-2"],
        "web_result": (
            "web_search('Four Tet production style IDM organic samples techniques'):\n"
            "→ BPM: 118–126 (oft House-Tempo, aber aufgebrochen)\n"
            "→ Signatur: Granulare Verarbeitung von akustischen Instrumenten\n"
            "→ Drums: real klingend aber stark bearbeitet, nicht quantisiert\n"
            "→ Harmonie: Jazz-artige Akkorde (Maj7, add9), warme Tonarten\n"
            "→ Textur: Polymer Granular auf Klavier/Gitarre-Samples\n"
            "→ Bass: subtil, Sinus-basiert, fast im Hintergrund"
        ),
        "audio_result": (
            "find_audio_example('Four Tet Rounds glitchy organic IDM 120 BPM'):\n"
            "→ BPM: 120 | Tonart: C major | Energie: 0.65\n"
            "→ Percussion: unregelmäßig, [0,3,7,9,13], nicht quantisiert\n"
            "→ Granular-Pad: Cmaj9-Akkord, Attack 1s, Grain 80ms"
        ),
        "note_plan": (
            "Notenplan Four-Tet-Stil (C major, 120 BPM):\n"
            "  Perc-Track: Kick=36 [s0,s7,s13], Snare=38 [s4,s12] — organisch, unquantisiert\n"
            "  Granular-Pad (Polymer): Cmaj7 = C4+E4+G4+B4 [s0,dur16], Grain 80ms, Spray 0.5\n"
            "  Bass (FM-4): C2 [s0,dur4], G2 [s8,dur4] — sehr subtil, vel=0.5"
        ),
    },
    "Bonobo": {
        "genre": "Downtempo / Trip Hop / Nu-Jazz",
        "bpm": "85–100",
        "key": "D minor",
        "style": "Live-Instrumente (Gitarre, Saxophon), Jazz-Akkorde, entspannte Grooves, atmosphärische Pads.",
        "devices": ["Polysynth (Piano/Keys)", "Sampler (Live-Instrumente)", "Phase-4 (Pad)", "FM-4 (Bass)", "Reverb", "EQ-5"],
        "web_result": (
            "web_search('Bonobo production style downtempo trip hop nu jazz techniques'):\n"
            "→ BPM: 85–100 (entspannt, swing-betont)\n"
            "→ Signatur: echte Instrumente samplen, nicht quantisieren\n"
            "→ Drums: real aufgenommene Drumkit-Samples, swing 55–60%\n"
            "→ Harmonie: Dm9, Fm11, Bb maj7 — Jazz-artige Progression\n"
            "→ Melodie: Flöte/Saxophon-Samples als Lead\n"
            "→ Tonart: D minor, A minor typisch"
        ),
        "audio_result": (
            "find_audio_example('Bonobo Kong downtempo groove 92 BPM D minor'):\n"
            "→ BPM: 92 | Tonart: D minor | Energie: 0.6\n"
            "→ Kick: [0,8,11], Snare: [4,12], Swing-HH: [1,3,5,7,9,11,13,15]\n"
            "→ Jazz-Akkord: Dm9 = D3+F3+A3+C4+E4"
        ),
        "note_plan": (
            "Notenplan Bonobo-Stil (D minor, 92 BPM):\n"
            "  Drums (Swing 60%): Kick=36 [s0,s8,s11], Snare=38 [s4,s12], HH=42 [alle Steps]\n"
            "  Keys (Polysynth): Dm9 = D3+F3+A3+C4+E4 [s0,dur8], Swing-Timing\n"
            "  Bass (FM-4): D2=38 [s0,dur4], A2=45 [s6,dur2], G2=43 [s10,dur2]\n"
            "  Pad (Phase-4): Dm7 gehalten, Attack 0.8s, Reverb Decay 4s"
        ),
    },
    "Flying Lotus": {
        "genre": "Future Bass / Experimental Hip Hop",
        "bpm": "80–95",
        "key": "G minor",
        "style": "Komplexe polyrhythmische Beats, Jazz-Harmonik, Glitch-Elemente, Bass-Heavy, Bewusstseinsstrom.",
        "devices": ["FM-4 (Sub-Bass)", "Polymer (Textur)", "Polysynth (Jazz-Chords)", "Phase-4 (Lead)", "Delay-2", "Reverb"],
        "web_result": (
            "web_search('Flying Lotus production style experimental hip hop polyrhythm techniques'):\n"
            "→ BPM: 80–95 (Hip-Hop-Tempo aber verschachtelt)\n"
            "→ Signatur: 3-über-4 Polyrhythmen (Kick in 3/4, Percussion in 4/4)\n"
            "→ Harmonie: erweiterte Jazz-Akkorde (Gm11, Cm9, Ebmaj7#11)\n"
            "→ Sub-Bass: sehr tief (G0–G1), 808-Style mit Pitch-Slides\n"
            "→ Textur: Granular aus Vinyl-Samples, 'cosmic' Sound\n"
            "→ Drums: nicht quantisiert, intentionale Fehler"
        ),
        "audio_result": (
            "find_audio_example('Flying Lotus Los Angeles beat 85 BPM G minor experimental'):\n"
            "→ BPM: 86 | Tonart: G minor | Energie: 0.8\n"
            "→ Kick: [0,3,6,9,12] — Triplet-Feel im 4/4\n"
            "→ Sub-Bass: G1=31 Slide→D2, 8-Beat-Sustain"
        ),
        "note_plan": (
            "Notenplan Flying-Lotus-Stil (G minor, 86 BPM):\n"
            "  Drums (Triplet in 4/4): Kick=36 [s0,s3,s6,s9,s12], Snare=38 [s4,s12]\n"
            "  Sub-Bass (FM-4): G1=31 [s0,dur8,Slide→D2=38], D2=38 [s8,dur4]\n"
            "  Jazz-Chords (Polysynth): Gm11 = G3+Bb3+D4+F4+A4 [s0,dur8]\n"
            "  Granular (Polymer): Vinyl-Textur, Grain 30ms, pitch-random"
        ),
    },
    "Moderat": {
        "genre": "Electro-Pop / IDM",
        "bpm": "120–130",
        "key": "A minor",
        "style": "Dunkle Elektro-Sounds, Gesang über pulsierenden Beats, industrielle Synthesizerklänge, Berlin-Atmosphäre.",
        "devices": ["Phase-4 (Industrial-Lead)", "FM-4 (Pulsierender Bass)", "Polysynth (Pad)", "Ladder-Filter", "Reverb", "Delay-2"],
        "web_result": (
            "web_search('Moderat production style electro pop IDM Berlin techniques'):\n"
            "→ BPM: 120–130 (variiert, oft 124–126)\n"
            "→ Signatur: Schwebende Vocals über harten Beats, Berlin-Melancholie\n"
            "→ Bass: pulsierend, synchron zum Kick, A minor Grundton\n"
            "→ Industrial Textur: metallische Percussion, Bitcrusher auf Snare\n"
            "→ Harmonie: Am → G → F → E (Moll, fallend) — typisch für Moderat\n"
            "→ Pad: lange Flächen (Phase-4), Attack 2s, subtil im Hintergrund"
        ),
        "audio_result": (
            "find_audio_example('Moderat Bad Kingdom beat 125 BPM A minor electro'):\n"
            "→ BPM: 125 | Tonart: A minor | Energie: 0.78\n"
            "→ 4-on-floor Kick: [0,4,8,12], Snare: [4,12], Industrial-HH: [2,10]\n"
            "→ Pulsierender Bass: A2=45 [s0,dur2], synchron Kick"
        ),
        "note_plan": (
            "Notenplan Moderat-Stil (A minor, 125 BPM):\n"
            "  Drums: 4-on-floor Kick=36 [s0,s4,s8,s12], Snare=38 [s4,s12], HH=42 [s2,s10]\n"
            "  Puls-Bass (FM-4): A2=45 [s0,dur2,s4,dur2,s8,dur2,s12,dur2] — synchron Kick\n"
            "  Akkorde (Polysynth): Am→G→F→E, je 4 Steps, Attack 2s\n"
            "  Industrial-Pad (Phase-4): A3 gehalten, Ladder-Filter resonant, leises Rauschen"
        ),
    },
}

# ── Song-Datenbank (web_search + find_audio_example direkt) ───────────────────

SONGS: dict[str, dict] = {
    "Under Pressure (Queen & David Bowie)": {
        "bpm": 117,
        "key": "D major",
        "style": "Rock/Pop, ikonische Bass-Intro, Vocal-Harmonien, dramatischer Aufbau.",
        "bassline_desc": "Die berühmte 4-Noten-Bassline: D3→D3→D3→Bb2→C3→D3 im Intro",
        "devices": ["FM-4 (Bass)", "Polysynth (Piano)", "Phase-4 (Synth)", "Reverb"],
        "web_result": (
            "web_search('Under Pressure Queen David Bowie chord progression BPM key bassline'):\n"
            "→ BPM: ~117 | Tonart: D major | Taktart: 4/4\n"
            "→ Ikonische Bassline-Intro: D3–D3–D3–Bb2–C3–D3 (MIDI: 62–62–62–58–60–62)\n"
            "→ Akkordfolge Vers: D–G–A–D\n"
            "→ Akkordfolge Bridge: Bb–C–D–Bb–C\n"
            "→ Piano-Chords: stabige Achtel-Noten, füllt die Harmonik\n"
            "→ Tempo-Feeling: straight, keine Swing"
        ),
        "audio_result": (
            "find_audio_example('Under Pressure Queen bassline 117 BPM D major'):\n"
            "→ BPM: 117 | Tonart: D major | Energie: 0.82\n"
            "→ Bass Intro-Pattern (16 Steps):\n"
            "  s0: D3=62 dur1, s2: D3=62 dur1, s4: D3=62 dur1\n"
            "  s5: Bb2=58 dur1, s6: C3=60 dur1, s8: D3=62 dur4\n"
            "→ Kick: [0,4,8,12], Snare: [4,12]"
        ),
        "note_plan": (
            "Notenplan Under Pressure (D major, 117 BPM):\n"
            "  Bass-Track (FM-4): Ikonische Bassline:\n"
            "    D3=62 [s0,dur1], D3=62 [s2,dur1], D3=62 [s4,dur1],\n"
            "    Bb2=58 [s5,dur1], C3=60 [s6,dur1], D3=62 [s8,dur4]\n"
            "  Drums: Kick=36 [s0,s4,s8,s12], Snare=38 [s4,s12]\n"
            "  Piano (Polysynth): D major Stab = D3+F#3+A3 [s0,dur2] auf jedem Beat\n"
            "  Akkordfolge: D–G–A–D (je 4 Steps pro Akkord)"
        ),
    },
    "Teardrop (Massive Attack)": {
        "bpm": 96,
        "key": "D minor",
        "style": "Trip Hop, langsamer hypnotischer Beat, Harfen-Intro, dunkle Atmosphäre, Elizabeth Fraser Vocals.",
        "devices": ["Sampler (Harfe/Cembalo)", "FM-4 (Sub-Bass)", "Phase-4 (Pad)", "Reverb", "Delay-2"],
        "web_result": (
            "web_search('Teardrop Massive Attack chord progression BPM production style'):\n"
            "→ BPM: ~96 | Tonart: D minor | Taktart: 4/4\n"
            "→ Harfen-Intro: Dm-Arpeggio, 16tel-Noten (D3–F3–A3–C4 wiederholt)\n"
            "→ Akkordfolge: Dm–Am–Bb–F–C (Trip-Hop Progression)\n"
            "→ Bass: tief, sinusförmig, D1–A1, sehr wenig Anschlag\n"
            "→ Drums: real klingende Breaks (Portishead-Stil), Swing\n"
            "→ Atmosphäre: langer Reverb auf allem"
        ),
        "audio_result": (
            "find_audio_example('Teardrop Massive Attack trip hop 96 BPM D minor breakbeat'):\n"
            "→ BPM: 96 | Tonart: D minor | Energie: 0.55\n"
            "→ Kick: [0,10], Snare: [4,14] — Break-Pattern, nicht quantisiert\n"
            "→ Harfen-Arpeggio: D3=50,F3=53,A3=57,C4=60 — je s0,s2,s4,s6 dur1"
        ),
        "note_plan": (
            "Notenplan Teardrop (D minor, 96 BPM):\n"
            "  Harfen-Arpeggio (Sampler): D3=50 [s0,dur1], F3=53 [s2,dur1], A3=57 [s4,dur1], C4=60 [s6,dur1]\n"
            "    → wiederholt s0–s6 in jeder Bar\n"
            "  Drums (unquantisiert): Kick=36 [s0,s10], Snare=38 [s4,s14]\n"
            "  Sub-Bass (FM-4): D1=26 [s0,dur8], A1=33 [s8,dur8]\n"
            "  Pad (Phase-4): Dm7 = D3+F3+A3+C4 gehalten, Reverb Decay 8s"
        ),
    },
    "Windowlicker (Aphex Twin)": {
        "bpm": 155,
        "key": "F# minor",
        "style": "IDM/Electronic, komplexe polyrhythmische Struktur, Acid-Bassline, glitchige Breaks.",
        "devices": ["FM-4 (Acid-Bass)", "Phase-4 (Lead)", "Polymer (Glitch)", "Ladder-Filter", "Saturator"],
        "web_result": (
            "web_search('Windowlicker Aphex Twin BPM key production techniques IDM'):\n"
            "→ BPM: ~155 | Tonart: F# minor | Taktart: 4/4 (mit polyrhythmischen Elementen)\n"
            "→ Acid-Bassline: TB-303-Stil, F#2 als Grundton, schnelle Filter-Sweeps\n"
            "→ Drums: stark verarbeitete Breaks, Bitcrusher, kein Standard-Pattern\n"
            "→ Signatur-Element: umgekehrte/manipulierte Vocals als Textur\n"
            "→ Energie: steigt kontinuierlich, viele automation sweeps"
        ),
        "audio_result": (
            "find_audio_example('Windowlicker Aphex Twin acid IDM 155 BPM F# minor'):\n"
            "→ BPM: 155 | Tonart: F# minor | Energie: 0.92\n"
            "→ Kick (unregelmäßig): [0,3,7,10,14]\n"
            "→ Acid-Bass: F#2=54 Slide→C#2=49, LFO auf Cutoff sehr schnell"
        ),
        "note_plan": (
            "Notenplan Windowlicker-Stil (F# minor, 155 BPM):\n"
            "  Drums (unregelmäßig): Kick=36 [s0,s3,s7,s10,s14], Snare=38 [s4,s11]\n"
            "  Acid-Bass (FM-4): F#2=54 [s0,dur3,Slide], C#2=49 [s4,dur2], A2=57 [s8,dur2]\n"
            "    → Ladder-Filter: sehr schneller LFO (Rate 1/8), Resonance 0.85\n"
            "  Glitch-Textur (Polymer): kurze Grain-Explosionen, Spray max"
        ),
    },
    "Midnight City (M83)": {
        "bpm": 103,
        "key": "E major",
        "style": "Synth-Pop/Dream Pop, 80er-Synthwave-Feeling, episches Saxophon-Solo, breite Stereo-Pads.",
        "devices": ["Phase-4 (80s Synth-Lead)", "Polysynth (Pad/Akkorde)", "FM-4 (Bass)", "Reverb", "Delay-2", "Compressor"],
        "web_result": (
            "web_search('Midnight City M83 chord progression BPM key synth pop production'):\n"
            "→ BPM: ~103 | Tonart: E major | Taktart: 4/4\n"
            "→ Akkordfolge: E–C#m–A–B (klassische 80s Pop-Progression)\n"
            "→ Signatur: breite Synth-Pads (Stereo-Chorus), Gated Reverb auf Snare\n"
            "→ Bass: elektronisch, synchron zum Kick, E2 als Grundton\n"
            "→ Lead: heller Synth-Arpeggio im Refrain\n"
            "→ Gated Reverb: charakteristisch 80s Sound auf Snare"
        ),
        "audio_result": (
            "find_audio_example('Midnight City M83 synth pop 103 BPM E major'):\n"
            "→ BPM: 103 | Tonart: E major | Energie: 0.88\n"
            "→ Kick: [0,4,8,12], Snare (Gated): [4,12], HH: [0,2,4,6,8,10,12,14]\n"
            "→ Synth-Bass: E2=40 [s0,dur4], B2=47 [s4,dur4] — synchron Kick"
        ),
        "note_plan": (
            "Notenplan Midnight City (E major, 103 BPM):\n"
            "  Drums: 4-on-floor Kick=36 [s0,s4,s8,s12], Snare=38 [s4,s12] (Gated Reverb!)\n"
            "  Bass (FM-4): E2=40 [s0,dur4], B2=47 [s4,dur4], A2=45 [s8,dur4], B2=47 [s12,dur4]\n"
            "  Pad (Polysynth): E major = E3+G#3+B3+E4 [s0,dur16], breiter Stereo-Chorus\n"
            "  Akkordfolge: E–C#m–A–B (je 4 Steps), Phase-4 Synth-Arpeggio im Refrain"
        ),
    },
    "Levels (Avicii)": {
        "bpm": 128,
        "key": "A major",
        "style": "Progressive House/EDM, euphorische Energie, Sample von Etta James, energetische Drops.",
        "devices": ["Phase-4 (Synth-Lead)", "Polysynth (Chord-Stabs)", "FM-4 (Bass)", "VD-Heavy Kick", "Compressor", "Reverb"],
        "web_result": (
            "web_search('Levels Avicii chord progression BPM production progressive house'):\n"
            "→ BPM: 128 | Tonart: A major | Taktart: 4/4\n"
            "→ Akkordfolge: A–F#m–D–E (I–vi–IV–V in A major)\n"
            "→ Lead: heller Synth-Stab (Supersaw), sehr breit chorused\n"
            "→ Drop: alle Elemente gleichzeitig, starker Sidechain-Pumping-Effekt\n"
            "→ Kick: klassischer 4-on-floor House-Kick, transient-betont\n"
            "→ Build-Up: Snare-Roll + Filter-Open über 8 Takte"
        ),
        "audio_result": (
            "find_audio_example('Levels Avicii drop 128 BPM A major progressive house'):\n"
            "→ BPM: 128 | Tonart: A major | Energie: 0.97\n"
            "→ 4-on-floor: Kick [0,4,8,12], Clap [4,12], HH 16tel [0..15]\n"
            "→ Supersaw-Lead: A4=69 [s0,dur4] — Akkordfolge A→F#m→D→E"
        ),
        "note_plan": (
            "Notenplan Levels (A major, 128 BPM):\n"
            "  Drums: 4-on-floor Kick=36 [s0,s4,s8,s12], Clap=39 [s4,s12], HH=42 [s0..s15]\n"
            "  Bass (FM-4): A2=45 [s0,dur4], F#2=42 [s4,dur4], D2=38 [s8,dur4], E2=40 [s12,dur4]\n"
            "  Supersaw-Lead (Phase-4): A4=69 [s0,dur4], F#4=66 [s4,dur4], D4=62 [s8,dur4], E4=64 [s12,dur4]\n"
            "    → Supersaw: 7 Voices, Detune 0.15, breiter Stereo-Chorus"
        ),
    },
    "Da Funk (Daft Punk)": {
        "bpm": 121,
        "key": "C minor",
        "style": "French House, verzerrter Distortion-Bass, minimale Struktur, stark gefiltert.",
        "devices": ["FM-4 (Distortion-Bass)", "Ladder-Filter", "Saturator", "VD-Kick", "Delay-2"],
        "web_result": (
            "web_search('Da Funk Daft Punk production bass distortion BPM French house'):\n"
            "→ BPM: 121 | Tonart: C minor | Taktart: 4/4\n"
            "→ Signatur: stark verzerrter Synth-Bass (E-Gitarren-ähnlich durch Fuzz)\n"
            "→ Bass-Phrase: C3–Bb2–G2–F2 mit starkem Fuzz-Distortion\n"
            "→ Drums: klassischer 4-on-floor, sehr tight und trocken\n"
            "→ Struktur: sehr minimal, Bass dominiert, kaum andere Elemente\n"
            "→ Filter: langsame HPF-Automation über mehrere Takte"
        ),
        "audio_result": (
            "find_audio_example('Da Funk Daft Punk distortion bass 121 BPM C minor'):\n"
            "→ BPM: 121 | Tonart: C minor | Energie: 0.83\n"
            "→ Kick: [0,4,8,12], Clap: [4,12] — tight, trocken\n"
            "→ Bass-Phrase: C3=48 [s0,dur2], Bb2=46 [s4,dur2], G2=43 [s8,dur2], F2=41 [s12,dur2]"
        ),
        "note_plan": (
            "Notenplan Da Funk (C minor, 121 BPM):\n"
            "  Drums: Kick=36 [s0,s4,s8,s12], Clap=39 [s4,s12] — trocken, kein Reverb\n"
            "  Distortion-Bass (FM-4 + Saturator):\n"
            "    C3=48 [s0,dur3], Bb2=46 [s4,dur3], G2=43 [s8,dur3], F2=41 [s12,dur3]\n"
            "    → Saturator Drive 0.7, Ladder-Filter Cutoff 600Hz langsam öffnend"
        ),
    },
}

# ── Frage-Templates für Künstler und Songs ─────────────────────────────────────

ARTIST_QUESTIONS = [
    "Ich würde gerne etwas wie {artist} machen",
    "Kannst du mir den Sound von {artist} erklären?",
    "Wie produziert {artist}?",
    "Zeig mir wie ich den Stil von {artist} in Bitwig nachahme",
    "Was macht den Sound von {artist} aus?",
    "Ich mag {artist} — wie produziere ich ähnliche Musik in Bitwig?",
    "Erkläre mir die Produktionstechniken von {artist}",
]

SONG_QUESTIONS = [
    "Kannst du {song} in Bitwig nachbauen?",
    "Ich möchte {song} nachproduzieren",
    "Zeig mir wie man {song} in Bitwig umsetzt",
    "Wie baue ich die Bassline von {song} nach?",
    "Analysiere {song} und hilf mir das in Bitwig umzusetzen",
    "Ich will einen Beat wie {song} — kannst du das in Bitwig aufsetzen?",
]

# ── Frage-Templates ────────────────────────────────────────────────────────────

INFO_QUESTIONS = [
    "{genre} würde mich interessieren",
    "Was ist {genre}?",
    "Erkläre mir {genre}",
    "Erzähl mir über {genre}",
    "Was sind die typischen Merkmale von {genre}?",
    "Welches Tempo hat {genre} normalerweise?",
    "Wie klingt {genre}?",
    "Was macht {genre} aus?",
    "Ich möchte mehr über {genre} lernen",
    "Kannst du mir {genre} erklären?",
]

DEVICE_QUESTIONS = [
    "Welche Bitwig-Instrumente brauche ich für {genre}?",
    "Welche Devices empfiehlst du für {genre}?",
    "Was für Synthesizer passen zu {genre}?",
    "Welche Plugins nutze ich am besten für {genre}-Bass?",
    "Womit erzeuge ich typischen {genre}-Sound in Bitwig?",
    "Welche FX-Kette ist typisch für {genre}?",
]

WORKFLOW_QUESTIONS = [
    "Wie erstelle ich einen {genre}-Track in Bitwig?",
    "Zeig mir den Ablauf für einen {genre}-Song",
    "Wie produziere ich {genre} in Bitwig?",
    "Welche Schritte brauche ich für {genre}?",
    "Wie setze ich {genre} in Bitwig um?",
    "Gib mir eine Anleitung für {genre}-Produktion",
]

ACTION_QUESTIONS = [
    "Erstelle einen {genre}-Beat in Bitwig",
    "Mach einen {genre}-Song",
    "Lege einen {genre}-Track an",
    "Ich will einen {genre}-Beat produzieren",
    "Baue mir ein {genre}-Setup in Bitwig auf",
]

# Fragen die KEIN Tool brauchen (Modell lernt Differenzierung)
NO_TOOL_QA = [
    {
        "user": "Was ist der Unterschied zwischen MIDI und Audio?",
        "assistant": (
            "MIDI ist Steuerungsdaten (Noten, Velocity, CC) — kein Ton, nur Befehle an Instrumente. "
            "Audio ist das aufgenommene Audiosignal (WAV, AIFF). In Bitwig: MIDI-Clips steuern "
            "Instrument-Devices, Audio-Clips spielen Samples ab. Du kannst MIDI live aufnehmen "
            "und nachträglich bearbeiten; Audio ist eine fertige Aufnahme."
        ),
    },
    {
        "user": "Was ist ein LFO?",
        "assistant": (
            "Ein LFO (Low Frequency Oscillator) ist ein Oszillator unter 20 Hz — zu langsam zum Hören, "
            "aber ideal zur Modulation. In Bitwig moduliert ein LFO z.B. den Cutoff-Filter (→ Wobble), "
            "die Lautstärke (→ Tremolo) oder das Pitch (→ Vibrato). "
            "Du findest ihn im Modulation-Bereich jedes Devices: einfach auf '+' klicken → LFO auswählen → "
            "Ziel-Parameter anklicken."
        ),
    },
    {
        "user": "Erkläre mir Sidechain-Compression",
        "assistant": (
            "Sidechain-Compression: Ein Compressor auf Track B wird vom Signal von Track A getriggert. "
            "Klassisch: Kick (Track A) duckt den Bass (Track B) — jedes Mal wenn die Kick schlägt, "
            "wird der Bass kurz leiser → 'Pumping'-Effekt, der im Club-Sound typisch ist.\n\n"
            "In Bitwig: Compressor auf Bass-Track → Sidechain-Input auf Kick-Track setzen → "
            "Ratio 8:1, Attack 1ms, Release 80ms."
        ),
    },
    {
        "user": "Was bedeutet BPM?",
        "assistant": (
            "BPM = Beats Per Minute — die Tempangabe in der Musik. 120 BPM bedeutet 120 Schläge pro Minute, "
            "also 2 pro Sekunde. In Bitwig stellst du das Tempo im Transport-Bereich oben ein. "
            "Typische Werte: Lo-fi 75–90, House 120–130, Techno 130–140, Drum and Bass 170–180 BPM."
        ),
    },
    {
        "user": "Wie funktioniert der Arranger in Bitwig?",
        "assistant": (
            "Der Arranger in Bitwig ist die Timeline-Ansicht (Shortcut: A). Hier ordnest du Clips in "
            "zeitlicher Abfolge an — Intro, Verse, Chorus, Outro. Im Gegensatz zum Clip Launcher (Session-View) "
            "ist der Arranger linear und exportierbar. Du kannst Clips aus dem Clip Launcher per Drag&Drop "
            "oder per Aufnahme in den Arranger überführen."
        ),
    },
    {
        "user": "Wie speichere ich ein Projekt in Bitwig?",
        "assistant": "Strg+S (Windows/Linux) oder Cmd+S (Mac) speichert das aktuelle Projekt. "
                     "Unter Datei → Speichern unter kannst du einen neuen Namen vergeben.",
    },
]


# ── Tool-Call Hilfsfunktionen ──────────────────────────────────────────────────

def make_tool_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:8]}"


def make_query_tool_call(query: str) -> dict:
    """Erstellt eine OpenAI-format tool_calls Nachricht."""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": make_tool_call_id(),
            "type": "function",
            "function": {
                "name": "query_bitwig_docs",
                "arguments": json.dumps({"query": query}, ensure_ascii=False),
            }
        }]
    }


def make_tool_result(tool_call_id: str, content: str) -> dict:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": content,
    }


def make_check_connection_tool_call() -> tuple[dict, str]:
    """Erstellt check_bitwig_connection Tool-Call + ID."""
    tc_id = make_tool_call_id()
    msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": tc_id,
            "type": "function",
            "function": {
                "name": "check_bitwig_connection",
                "arguments": "{}",
            }
        }]
    }
    return msg, tc_id


# ── Pair-Generatoren ───────────────────────────────────────────────────────────

def generate_info_pair(genre: str, g: dict, question_template: str) -> dict:
    """User fragt nach Genre → query_bitwig_docs → Antwort."""
    question = question_template.format(genre=genre)
    query = f"{genre} genre characteristics BPM instruments Bitwig"

    tc_id = make_tool_call_id()
    tool_call_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": tc_id,
            "type": "function",
            "function": {
                "name": "query_bitwig_docs",
                "arguments": json.dumps({"query": query}, ensure_ascii=False),
            }
        }]
    }
    tool_result_msg = make_tool_result(tc_id, g["neo4j_result"])

    final_answer = (
        f"{genre} ist ein Musik-Genre mit folgenden Merkmalen:\n\n"
        f"**Tempo:** {g['bpm']} BPM\n"
        f"**Tonart:** meist {g['key']}\n"
        f"**Charakteristik:** {g['characteristics']}\n\n"
        f"**Empfohlene Bitwig-Devices:**\n"
        + "\n".join(f"  - {d}" for d in g["devices"])
        + f"\n\nMöchtest du einen {genre}-Track direkt in Bitwig anlegen?"
    )

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": question},
        tool_call_msg,
        tool_result_msg,
        {"role": "assistant", "content": final_answer},
    ]}


def generate_device_pair(genre: str, g: dict, question_template: str) -> dict:
    """User fragt nach Devices → query_bitwig_docs → Device-Liste."""
    question = question_template.format(genre=genre)
    query = f"{genre} Bitwig devices instruments synthesizer FX"

    tc_id = make_tool_call_id()
    tool_call_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": tc_id,
            "type": "function",
            "function": {
                "name": "query_bitwig_docs",
                "arguments": json.dumps({"query": query}, ensure_ascii=False),
            }
        }]
    }
    tool_result_msg = make_tool_result(tc_id, g["neo4j_result"])

    device_lines = "\n".join(f"  - **{d}**" for d in g["devices"])
    final_answer = (
        f"Für {genre} ({g['bpm']} BPM) empfehle ich folgende Bitwig-Devices:\n\n"
        f"{device_lines}\n\n"
        f"Die Datenbank zeigt:\n{g['neo4j_result']}\n\n"
        f"Soll ich das Setup direkt in Bitwig anlegen?"
    )

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": question},
        tool_call_msg,
        tool_result_msg,
        {"role": "assistant", "content": final_answer},
    ]}


def generate_workflow_pair(genre: str, g: dict, question_template: str) -> dict:
    """User fragt nach Workflow → query_bitwig_docs → Schritt-für-Schritt."""
    question = question_template.format(genre=genre)
    query = f"{genre} workflow Bitwig production steps devices setup"

    tc_id = make_tool_call_id()
    tool_call_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": tc_id,
            "type": "function",
            "function": {
                "name": "query_bitwig_docs",
                "arguments": json.dumps({"query": query}, ensure_ascii=False),
            }
        }]
    }
    tool_result_msg = make_tool_result(tc_id, g["neo4j_result"])

    bpm = g["bpm"].split("–")[0]  # Untergrenze
    final_answer = (
        f"**{genre}-Produktion in Bitwig — Schritt für Schritt:**\n\n"
        f"1. `check_bitwig_connection` — Bridge prüfen\n"
        f"2. Tempo setzen: **{bpm} BPM** (Untergrenze für {genre})\n"
        f"3. Tracks anlegen via `execute_setup`:\n"
        + "\n".join(f"   - {d}" for d in g["devices"][:4])
        + f"\n4. Drum-Pattern schreiben (`write_pattern`)\n"
        f"5. Bassline schreiben\n"
        f"6. `get_bitwig_track_state` — Projektstatus prüfen\n\n"
        f"Soll ich direkt loslegen?"
    )

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": question},
        tool_call_msg,
        tool_result_msg,
        {"role": "assistant", "content": final_answer},
    ]}


def generate_action_pair(genre: str, g: dict, question_template: str) -> dict:
    """User will Song erstellen → check_connection + query → execute_setup-Plan."""
    question = question_template.format(genre=genre)
    query = f"{genre} Bitwig devices BPM setup tracks"

    bpm_str = g["bpm"]
    bpm_val = int(bpm_str.split("–")[0]) + 5  # Mittlerer Wert

    # Tool-Call 1: check_bitwig_connection
    tc_id_1 = make_tool_call_id()
    check_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": tc_id_1,
            "type": "function",
            "function": {"name": "check_bitwig_connection", "arguments": "{}"},
        }]
    }
    check_result = make_tool_result(tc_id_1, "connected: true | BitwigStepPlugin Port 8002 erreichbar")

    # Tool-Call 2: query_bitwig_docs
    tc_id_2 = make_tool_call_id()
    query_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": tc_id_2,
            "type": "function",
            "function": {
                "name": "query_bitwig_docs",
                "arguments": json.dumps({"query": query}, ensure_ascii=False),
            }
        }]
    }
    query_result = make_tool_result(tc_id_2, g["neo4j_result"])

    # execute_setup Plan als Text-Antwort
    steps_preview = "\n".join(
        f'  {{"type": "add_track", "args": {{}}}},\n  {{"type": "load_instrument", "args": {{"name": "{d.split("(")[0].strip()}"}}}}'
        for d in g["devices"][:3]
    )
    final_answer = (
        f"Bitwig ist erreichbar. Lege {genre}-Setup an ({bpm_val} BPM, {g['key']}):\n\n"
        f"```json\n"
        f'{{"context_type": "song", "target": {{"bpm": {bpm_val}, "genre": "{genre}"}},\n'
        f' "summary": "{genre} Beat", "steps": [\n'
        f'  {{"type": "set_tempo", "args": {{"bpm": {bpm_val}}}}},\n'
        f"{steps_preview}\n"
        f"]}}\n```\n\n"
        f"Führe ich `execute_setup` mit diesem Plan aus?"
    )

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": question},
        check_msg,
        check_result,
        query_msg,
        query_result,
        {"role": "assistant", "content": final_answer},
    ]}


def generate_gap_detection_pair(genre: str, g: dict) -> dict:
    """KB-Lücke erkannt → web_search + find_audio_example → Notenplan."""
    question = random.choice([
        f"Erstelle einen {genre}-Beat in Bitwig",
        f"Ich will einen {genre}-Song produzieren",
        f"Mach mir ein {genre}-Setup",
        f"{genre} würde mich interessieren — kannst du einen Beat bauen?",
    ])

    # Tool-Call 1: query_bitwig_docs (gibt lückenhaftes Ergebnis)
    tc1 = make_tool_call_id()
    query_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc1, "type": "function", "function": {
            "name": "query_bitwig_docs",
            "arguments": json.dumps({"query": f"{genre} genre devices BPM Bitwig"}, ensure_ascii=False),
        }}],
    }
    query_result = make_tool_result(tc1, g["neo4j_result_partial"])

    # Tool-Call 2: web_search (Fallback wegen Lücke)
    tc2 = make_tool_call_id()
    web_msg = {
        "role": "assistant",
        "content": "Die KB hat Lücken für dieses Genre. Ich hole stilistisches Wissen aus dem Web.",
        "tool_calls": [{"id": tc2, "type": "function", "function": {
            "name": "web_search",
            "arguments": json.dumps(
                {"query": f"{genre} drum pattern chord progression typical BPM"},
                ensure_ascii=False,
            ),
        }}],
    }
    web_result = make_tool_result(tc2, g["web_result"])

    # Tool-Call 3: find_audio_example (konkrete Onset-Steps)
    tc3 = make_tool_call_id()
    audio_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc3, "type": "function", "function": {
            "name": "find_audio_example",
            "arguments": json.dumps({"genre_query": f"{genre} drum loop {g['bpm'].split('–')[0]} BPM"}, ensure_ascii=False),
        }}],
    }
    audio_result = make_tool_result(tc3, g["audio_result"])

    # Notenplan als nächste Antwort (BEVOR check_connection)
    plan_answer = (
        f"Ich habe jetzt genug Wissen für {genre}. Mein Notenplan:\n\n"
        f"{g['note_plan']}\n\n"
        f"Jetzt prüfe ich die Bitwig-Verbindung und lege die Tracks an."
    )

    # Tool-Call 4: check_bitwig_connection
    tc4 = make_tool_call_id()
    check_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc4, "type": "function", "function": {
            "name": "check_bitwig_connection", "arguments": "{}",
        }}],
    }
    check_result = make_tool_result(tc4, "connected: true | BitwigStepPlugin Port 8002 erreichbar")

    bpm_val = int(g["bpm"].split("–")[0]) + 5
    final_answer = (
        f"Bitwig verbunden. Lege {genre}-Setup an ({bpm_val} BPM, {g['key']}) "
        f"basierend auf dem Notenplan — rufe jetzt `execute_setup` auf."
    )

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": question},
        query_msg, query_result,
        web_msg,   web_result,
        audio_msg, audio_result,
        {"role": "assistant", "content": plan_answer},
        check_msg, check_result,
        {"role": "assistant", "content": final_answer},
    ]}


def generate_full_production_pair(genre: str, g: dict) -> dict:
    """Vollständige Produktionskette: query→web→plan→check→setup→write→tipps."""
    question = random.choice([
        f"Produziere einen kompletten {genre}-Beat",
        f"Erstelle einen {genre}-Song mit Drums, Bass und Melodie",
        f"Ich will einen {genre}-Track — mach alles komplett",
        f"Baue mir einen fertigen {genre}-Beat in Bitwig",
    ])

    bpm_val = int(g["bpm"].split("–")[0]) + 5
    key = g["key"]
    devices = g["devices"]

    # Phase 1: query_bitwig_docs
    tc1 = make_tool_call_id()
    q_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc1, "type": "function", "function": {
            "name": "query_bitwig_docs",
            "arguments": json.dumps({"query": f"{genre} devices BPM Bitwig setup"}, ensure_ascii=False),
        }}],
    }
    q_result = make_tool_result(tc1, g["neo4j_result"])

    # Notenplan-Antwort nach query
    bass_device = next((d for d in devices if "FM-4" in d or "Bass" in d), devices[0])
    drum_device = next((d for d in devices if "Kick" in d or "VD-" in d or "Drum" in d), "VD-Heavy Kick")
    lead_device = next((d for d in devices if "Phase-4" in d or "Polysynth" in d), devices[-1])

    plan_msg_content = (
        f"KB-Ergebnis ausgewertet. Mein Notenplan für {genre} ({bpm_val} BPM, {key}):\n\n"
        f"**Track 1 — Drums** ({drum_device.split('(')[0].strip()}): "
        f"Kick=36 [s0,s8], Snare=38 [s4,s12], HH=42 [s2,s6,s10,s14]\n"
        f"**Track 2 — Bass** ({bass_device.split('(')[0].strip()}): "
        f"Root+Quint-Pattern, 4 Steps je Note\n"
        f"**Track 3 — Lead** ({lead_device.split('(')[0].strip()}): "
        f"Diatonische Phrase in {key}, Oktave 4\n\n"
        f"Notenplan steht — jetzt Bitwig-Verbindung prüfen."
    )

    # Phase 3a: check_connection
    tc2 = make_tool_call_id()
    check_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc2, "type": "function", "function": {
            "name": "check_bitwig_connection", "arguments": "{}",
        }}],
    }
    check_result = make_tool_result(tc2, "connected: true | BitwigStepPlugin Port 8002 erreichbar")

    # Phase 3b: execute_setup
    tc3 = make_tool_call_id()
    setup_args = {
        "result": {
            "context_type": "song",
            "target": {"bpm": bpm_val, "genre": genre},
            "summary": f"{genre} Beat",
            "steps": [
                {"type": "set_tempo",       "args": {"bpm": bpm_val},                                              "status": "pending", "note": ""},
                {"type": "add_track",       "args": {"track_type": "instrument"},                                  "status": "pending", "note": "Drums"},
                {"type": "load_instrument", "args": {"track_index": 1, "name": drum_device.split("(")[0].strip()}, "status": "pending", "note": ""},
                {"type": "add_track",       "args": {"track_type": "instrument"},                                  "status": "pending", "note": "Bass"},
                {"type": "load_instrument", "args": {"track_index": 2, "name": bass_device.split("(")[0].strip()}, "status": "pending", "note": ""},
                {"type": "add_track",       "args": {"track_type": "instrument"},                                  "status": "pending", "note": "Lead"},
                {"type": "load_instrument", "args": {"track_index": 3, "name": lead_device.split("(")[0].strip()},"status": "pending", "note": ""},
            ],
        }
    }
    setup_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc3, "type": "function", "function": {
            "name": "execute_setup",
            "arguments": json.dumps(setup_args, ensure_ascii=False),
        }}],
    }
    setup_result = make_tool_result(tc3, f"OK — 3 Tracks angelegt | Tempo: {bpm_val} BPM | Bitwig-Status: 3 Track(s)")

    # Phase 3c: write_pattern Drums
    tc4 = make_tool_call_id()
    drum_notes = [
        {"pitch": 36, "step": 0,  "duration": 2, "velocity": 0.9, "channel": 9},
        {"pitch": 38, "step": 4,  "duration": 2, "velocity": 0.85, "channel": 9},
        {"pitch": 36, "step": 8,  "duration": 2, "velocity": 0.9, "channel": 9},
        {"pitch": 38, "step": 12, "duration": 2, "velocity": 0.85, "channel": 9},
        {"pitch": 42, "step": 2,  "duration": 1, "velocity": 0.5, "channel": 9},
        {"pitch": 42, "step": 6,  "duration": 1, "velocity": 0.5, "channel": 9},
        {"pitch": 42, "step": 10, "duration": 1, "velocity": 0.5, "channel": 9},
        {"pitch": 42, "step": 14, "duration": 1, "velocity": 0.5, "channel": 9},
    ]
    write_drums_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc4, "type": "function", "function": {
            "name": "write_pattern",
            "arguments": json.dumps(
                {"track_index": 1, "notes": drum_notes, "bpm": bpm_val, "key": key},
                ensure_ascii=False,
            ),
        }}],
    }
    write_drums_result = make_tool_result(tc4, "OK — 8 Noten geschrieben (Track 1 Drums)")

    # Phase 3d: write_pattern Bass
    root_midi = {"C": 48, "D": 50, "E": 52, "F": 53, "G": 55, "A": 57, "B": 59,
                 "D#": 51, "F#": 54, "A#": 58}.get(key.split()[0], 50) - 12
    tc5 = make_tool_call_id()
    bass_notes = [
        {"pitch": root_midi,      "step": 0,  "duration": 4, "velocity": 0.8, "channel": 0},
        {"pitch": root_midi + 7,  "step": 4,  "duration": 4, "velocity": 0.75, "channel": 0},
        {"pitch": root_midi,      "step": 8,  "duration": 4, "velocity": 0.8, "channel": 0},
        {"pitch": root_midi + 5,  "step": 12, "duration": 4, "velocity": 0.75, "channel": 0},
    ]
    write_bass_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc5, "type": "function", "function": {
            "name": "write_pattern",
            "arguments": json.dumps(
                {"track_index": 2, "notes": bass_notes, "bpm": bpm_val, "key": key},
                ensure_ascii=False,
            ),
        }}],
    }
    write_bass_result = make_tool_result(tc5, "OK — 4 Noten geschrieben (Track 2 Bass)")

    # Tipps als Abschluss
    tip_device = devices[2] if len(devices) > 2 else devices[-1]
    final_tips = (
        f"**{genre}-Beat fertig!** 3 Tracks in Bitwig, {bpm_val} BPM, {key}.\n\n"
        f"**Tipps:**\n"
        f"- Sidechain: Compressor auf Bass-Track, Sidechain-Input = Kick → Pumping-Effekt\n"
        f"- {tip_device.split('(')[0].strip()}: {g['neo4j_result'].split(chr(10))[3].strip() if len(g['neo4j_result'].split(chr(10))) > 3 else 'Parameter nach Geschmack anpassen'}\n"
        f"- `validate_and_learn` aufrufen um den Beat zu bewerten und in Neo4j zu speichern\n"
        f"- `suggest_notes` für Launchpad-Hervorhebung der passenden Noten"
    )

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": question},
        q_msg,          q_result,
        {"role": "assistant", "content": plan_msg_content},
        check_msg,      check_result,
        setup_msg,      setup_result,
        write_drums_msg, write_drums_result,
        write_bass_msg,  write_bass_result,
        {"role": "assistant", "content": final_tips},
    ]}


def generate_artist_pair(artist: str, a: dict, question_template: str) -> dict:
    """Künstler-Anfrage → web_search DIREKT (kein query_bitwig_docs — KB hat keine Künstlerdaten)."""
    question = question_template.format(artist=artist)

    # Tool-Call 1: web_search (NICHT query_bitwig_docs!)
    tc1 = make_tool_call_id()
    web_msg = {
        "role": "assistant",
        "content": f"{artist} ist ein Künstler — diese Information ist nicht in der Bitwig-KB, ich suche im Web.",
        "tool_calls": [{"id": tc1, "type": "function", "function": {
            "name": "web_search",
            "arguments": json.dumps(
                {"query": f"{artist} production style techniques {a['genre']} BPM"},
                ensure_ascii=False,
            ),
        }}],
    }
    web_result = make_tool_result(tc1, a["web_result"])

    # Tool-Call 2: find_audio_example (konkrete Onset-Pattern)
    tc2 = make_tool_call_id()
    audio_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc2, "type": "function", "function": {
            "name": "find_audio_example",
            "arguments": json.dumps(
                {"genre_query": f"{artist} {a['genre']} {a['bpm'].split('–')[0]} BPM"},
                ensure_ascii=False,
            ),
        }}],
    }
    audio_result = make_tool_result(tc2, a["audio_result"])

    # Tool-Call 3: store_result_in_kb
    tc3 = make_tool_call_id()
    devices_list = a["devices"]
    store_msg = {
        "role": "assistant",
        "content": "Gutes Ergebnis — speichere es in der KB für zukünftige Anfragen.",
        "tool_calls": [{"id": tc3, "type": "function", "function": {
            "name": "store_result_in_kb",
            "arguments": json.dumps({"data": {
                "type": "artist",
                "name": artist,
                "genre": a["genre"],
                "bpm": a["bpm"],
                "key": a["key"],
                "style": a["style"],
                "devices": devices_list,
                "note_plan": a["note_plan"],
                "source": f"web_search: {artist} production style",
            }}, ensure_ascii=False),
        }}],
    }
    store_result = make_tool_result(tc3, f"✓ Artist '{artist}' gespeichert (Score: 1.00)")

    # Abschluss-Antwort
    device_lines = "\n".join(f"  - {d}" for d in devices_list)
    final_answer = (
        f"**{artist}-Stil in Bitwig ({a['genre']}, {a['bpm']} BPM, {a['key']}):**\n\n"
        f"**Charakteristik:** {a['style']}\n\n"
        f"**Empfohlene Bitwig-Devices:**\n{device_lines}\n\n"
        f"**Notenplan:**\n{a['note_plan']}\n\n"
        f"Das Profil ist jetzt in der KB gespeichert — beim nächsten Mal direkt verfügbar.\n"
        f"Soll ich das Setup in Bitwig anlegen?"
    )

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": question},
        web_msg,    web_result,
        audio_msg,  audio_result,
        store_msg,  store_result,
        {"role": "assistant", "content": final_answer},
    ]}


def generate_song_pair(song: str, s: dict, question_template: str) -> dict:
    """Song-Rekonstruktion → web_search + find_audio_example DIREKT → Notenplan → optional Bitwig."""
    question = question_template.format(song=song)

    # Tool-Call 1: web_search (Song-Daten — nicht in KB)
    tc1 = make_tool_call_id()
    web_msg = {
        "role": "assistant",
        "content": f"Song-spezifische Daten ({song}) sind nicht in der Bitwig-KB — ich suche Akkordfolge, BPM und Key im Web.",
        "tool_calls": [{"id": tc1, "type": "function", "function": {
            "name": "web_search",
            "arguments": json.dumps(
                {"query": f"{song} chord progression BPM key music theory analysis"},
                ensure_ascii=False,
            ),
        }}],
    }
    web_result = make_tool_result(tc1, s["web_result"])

    # Tool-Call 2: find_audio_example (Timing und Noten-Pattern)
    tc2 = make_tool_call_id()
    audio_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc2, "type": "function", "function": {
            "name": "find_audio_example",
            "arguments": json.dumps(
                {"genre_query": f"{song} {s['bpm']} BPM {s['key']}"},
                ensure_ascii=False,
            ),
        }}],
    }
    audio_result = make_tool_result(tc2, s["audio_result"])

    # Notenplan
    plan_answer = (
        f"Ich habe genug Daten für **{song}** ({s['bpm']} BPM, {s['key']}).\n\n"
        f"**Notenplan:**\n{s['note_plan']}\n\n"
        f"Jetzt prüfe ich die Bitwig-Verbindung und lege die Tracks an."
    )

    # Tool-Call 3: check_bitwig_connection
    tc3 = make_tool_call_id()
    check_msg = {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": tc3, "type": "function", "function": {
            "name": "check_bitwig_connection", "arguments": "{}",
        }}],
    }
    check_result = make_tool_result(tc3, "connected: true | BitwigStepPlugin Port 8002 erreichbar")

    # Tool-Call 4: store_result_in_kb
    tc4 = make_tool_call_id()
    store_msg = {
        "role": "assistant",
        "content": "Speichere die Song-Analyse in der KB für zukünftige Anfragen.",
        "tool_calls": [{"id": tc4, "type": "function", "function": {
            "name": "store_result_in_kb",
            "arguments": json.dumps({"data": {
                "type": "song",
                "name": song.split("(")[0].strip(),
                "artist": song.split("(")[1].rstrip(")").strip() if "(" in song else "",
                "bpm": s["bpm"],
                "key": s["key"],
                "chord_progression": s.get("web_result","").split("Akkordfolge: ")[-1].split("\n")[0] if "Akkordfolge" in s.get("web_result","") else "",
                "note_plan": s["note_plan"],
                "source": f"web_search: {song} chord progression",
            }}, ensure_ascii=False),
        }}],
    }
    store_result = make_tool_result(tc4, f"✓ Song '{song}' gespeichert (Score: 1.00)")

    device_lines = "\n".join(f"  - {d}" for d in s["devices"])
    final_answer = (
        f"Bitwig verbunden. Lege **{song}**-Rekonstruktion an ({s['bpm']} BPM, {s['key']}).\n\n"
        f"**Devices:**\n{device_lines}\n\n"
        f"Song-Analyse ist in der KB gespeichert — beim nächsten Mal direkt verfügbar.\n"
        f"Führe jetzt `execute_setup` aus und schreibe die Noten aus dem Plan."
    )

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": question},
        web_msg,   web_result,
        audio_msg, audio_result,
        {"role": "assistant", "content": plan_answer},
        check_msg, check_result,
        store_msg, store_result,
        {"role": "assistant", "content": final_answer},
    ]}


def generate_no_tool_pair(qa: dict) -> dict:
    """Allgemeine Frage → direkte Antwort ohne Tool-Call."""
    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": qa["user"]},
        {"role": "assistant", "content": qa["assistant"]},
    ]}


# ── Haupt-Generator ────────────────────────────────────────────────────────────

def generate_all_pairs() -> list[dict]:
    pairs = []

    for genre, g in GENRES.items():
        # Info-Paare (je 3 zufällige Fragen)
        for tmpl in random.sample(INFO_QUESTIONS, min(3, len(INFO_QUESTIONS))):
            pairs.append(generate_info_pair(genre, g, tmpl))

        # Device-Paare (je 2)
        for tmpl in random.sample(DEVICE_QUESTIONS, min(2, len(DEVICE_QUESTIONS))):
            pairs.append(generate_device_pair(genre, g, tmpl))

        # Workflow-Paare (je 2)
        for tmpl in random.sample(WORKFLOW_QUESTIONS, min(2, len(WORKFLOW_QUESTIONS))):
            pairs.append(generate_workflow_pair(genre, g, tmpl))

        # Action-Paare (je 2) — einfache Kette
        for tmpl in random.sample(ACTION_QUESTIONS, min(2, len(ACTION_QUESTIONS))):
            pairs.append(generate_action_pair(genre, g, tmpl))

        # Full-Production-Paare (je 1 pro Genre) — komplette Kette mit write_pattern + Tipps
        pairs.append(generate_full_production_pair(genre, g))

    # Gap-Detection-Paare (für Genres mit lückenhaftem KB)
    for genre, g in GENRES_WITH_GAPS.items():
        for _ in range(2):  # 2 Variationen pro Genre
            pairs.append(generate_gap_detection_pair(genre, g))

    # Künstler-Paare (web_search DIREKT — kein KB-Aufruf)
    for artist, a in ARTISTS.items():
        for tmpl in random.sample(ARTIST_QUESTIONS, min(3, len(ARTIST_QUESTIONS))):
            pairs.append(generate_artist_pair(artist, a, tmpl))

    # Song-Paare (web_search + find_audio_example DIREKT)
    for song, s in SONGS.items():
        for tmpl in random.sample(SONG_QUESTIONS, min(3, len(SONG_QUESTIONS))):
            pairs.append(generate_song_pair(song, s, tmpl))

    # No-Tool-Paare (alle)
    for qa in NO_TOOL_QA:
        pairs.append(generate_no_tool_pair(qa))

    return pairs


def validate_pairs(pairs: list[dict]) -> None:
    """Prüft Format-Konsistenz aller generierten Paare."""
    errors = 0
    for i, p in enumerate(pairs):
        msgs = p.get("messages", [])
        if not msgs:
            print(f"[FEHLER] Pair {i}: leer")
            errors += 1
            continue
        for m in msgs:
            if m["role"] == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    if "id" not in tc or "function" not in tc:
                        print(f"[FEHLER] Pair {i}: tool_call fehlt id/function")
                        errors += 1
                    args = tc["function"].get("arguments", "")
                    try:
                        json.loads(args)
                    except json.JSONDecodeError:
                        print(f"[FEHLER] Pair {i}: arguments kein gültiges JSON: {args}")
                        errors += 1
            if m["role"] == "tool" and "tool_call_id" not in m:
                print(f"[FEHLER] Pair {i}: tool-message ohne tool_call_id")
                errors += 1
    if errors == 0:
        print(f"  ✓ Alle {len(pairs)} Paare valide")
    else:
        print(f"  ✗ {errors} Fehler gefunden")


if __name__ == "__main__":
    out_dir = Path(__file__).parent.parent / "data" / "training"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "tool_call_pairs.jsonl"

    print("=== Tool-Call Pairs Generator ===\n")
    pairs = generate_all_pairs()
    random.shuffle(pairs)

    print(f"Generiert: {len(pairs)} Paare")

    # Statistik
    with_tool_calls = sum(
        1 for p in pairs
        if any("tool_calls" in m for m in p["messages"])
    )
    no_tool = len(pairs) - with_tool_calls
    print(f"  Mit tool_calls:  {with_tool_calls}")
    print(f"  Ohne tool_calls: {no_tool} (No-Tool-Paare)")

    # Typen zählen
    type_counts = {"info": 0, "device": 0, "workflow": 0, "action": 0, "no_tool": 0}
    for p in pairs:
        msgs = p["messages"]
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        n_tool_calls = sum(1 for m in msgs if m.get("tool_calls"))
        if n_tool_calls == 0:
            type_counts["no_tool"] += 1
        elif n_tool_calls >= 2:
            type_counts["action"] += 1
        elif "Devices" in next((m["content"] or "" for m in msgs if m["role"] == "assistant" and not m.get("tool_calls")), ""):
            type_counts["device"] += 1
        elif "Schritt" in next((m["content"] or "" for m in msgs if m["role"] == "assistant" and not m.get("tool_calls")), ""):
            type_counts["workflow"] += 1
        else:
            type_counts["info"] += 1

    print("\nPaare nach Typ:")
    for t, n in type_counts.items():
        print(f"  {t:12s}: {n}")

    print("\nFormat-Validierung:")
    validate_pairs(pairs)

    out_file.write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n",
        encoding="utf-8",
    )
    print(f"\n✓ {out_file} ({len(pairs)} Zeilen)")
    print("\nNächster Schritt: python scripts/prepare_mlx_training.py")
