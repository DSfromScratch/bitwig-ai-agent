"""Ingestiert kuratierte MIDI-Drum-Patterns in Neo4j als Pattern-Nodes.

Idempotent: MERGE on id — mehrfaches Ausführen sicher.

Run from repo root:
    .venv/bin/python scripts/ingest_patterns.py
"""
from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Pattern-Daten ──────────────────────────────────────────────────────────────
# Format: step=Beat-Position, pitch=MIDI, vel=0.0-1.0, dur=Beats
# Pitches: kick=36 snare=38 hihat=42 clap=39 openhat=46
#
# Längen: kick=8 beats (2-Bar-Charakter bei DnB), snare/hihat/clap=4 beats
# _expand_notes in assemble.py füllt auf target_beats auf.

PATTERNS: list[dict] = [

    # ── DRUM AND BASS ──────────────────────────────────────────────────────────
    # Charakteristik: synkopierter Two-Step Kick, Backbeat-Snare mit Ghost-Noten,
    #                 dichte 16tel Hi-Hats

    {
        "id": "dnb_kick_twostep_a",
        "genre": "drum and bass",
        "role": "kick",
        "length_beats": 8.0,
        "description": "DnB Two-Step Kick — Classic",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.95, "dur": 0.25},
            {"step": 1.5,  "pitch": 36, "vel": 0.85, "dur": 0.25},
            {"step": 2.0,  "pitch": 36, "vel": 0.90, "dur": 0.25},
            {"step": 3.5,  "pitch": 36, "vel": 0.80, "dur": 0.25},
            {"step": 4.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
            {"step": 5.5,  "pitch": 36, "vel": 0.82, "dur": 0.25},
            {"step": 6.0,  "pitch": 36, "vel": 0.88, "dur": 0.25},
            {"step": 7.5,  "pitch": 36, "vel": 0.78, "dur": 0.25},
        ],
    },
    {
        "id": "dnb_kick_twostep_b",
        "genre": "drum and bass",
        "role": "kick",
        "length_beats": 8.0,
        "description": "DnB Two-Step Kick — Synkopiert mit Extra-Hits",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.95, "dur": 0.25},
            {"step": 0.75, "pitch": 36, "vel": 0.55, "dur": 0.25},
            {"step": 1.5,  "pitch": 36, "vel": 0.82, "dur": 0.25},
            {"step": 3.0,  "pitch": 36, "vel": 0.72, "dur": 0.25},
            {"step": 3.5,  "pitch": 36, "vel": 0.85, "dur": 0.25},
            {"step": 4.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
            {"step": 5.5,  "pitch": 36, "vel": 0.80, "dur": 0.25},
            {"step": 6.5,  "pitch": 36, "vel": 0.68, "dur": 0.25},
            {"step": 7.5,  "pitch": 36, "vel": 0.75, "dur": 0.25},
        ],
    },
    {
        "id": "dnb_snare_ghost_a",
        "genre": "drum and bass",
        "role": "snare",
        "length_beats": 4.0,
        "description": "DnB Snare — Backbeat mit Ghost-Noten",
        "notes": [
            {"step": 0.5,  "pitch": 38, "vel": 0.28, "dur": 0.1},
            {"step": 0.75, "pitch": 38, "vel": 0.35, "dur": 0.1},
            {"step": 1.0,  "pitch": 38, "vel": 0.88, "dur": 0.1},
            {"step": 2.5,  "pitch": 38, "vel": 0.32, "dur": 0.1},
            {"step": 2.75, "pitch": 38, "vel": 0.38, "dur": 0.1},
            {"step": 3.0,  "pitch": 38, "vel": 0.85, "dur": 0.1},
        ],
    },
    {
        "id": "dnb_snare_ghost_b",
        "genre": "drum and bass",
        "role": "snare",
        "length_beats": 4.0,
        "description": "DnB Snare — Dichte Ghost-Runs vor Backbeat",
        "notes": [
            {"step": 0.25, "pitch": 38, "vel": 0.22, "dur": 0.1},
            {"step": 0.5,  "pitch": 38, "vel": 0.28, "dur": 0.1},
            {"step": 0.75, "pitch": 38, "vel": 0.35, "dur": 0.1},
            {"step": 0.875,"pitch": 38, "vel": 0.42, "dur": 0.1},
            {"step": 1.0,  "pitch": 38, "vel": 0.90, "dur": 0.1},
            {"step": 1.75, "pitch": 38, "vel": 0.25, "dur": 0.1},
            {"step": 2.25, "pitch": 38, "vel": 0.22, "dur": 0.1},
            {"step": 2.5,  "pitch": 38, "vel": 0.30, "dur": 0.1},
            {"step": 2.75, "pitch": 38, "vel": 0.38, "dur": 0.1},
            {"step": 2.875,"pitch": 38, "vel": 0.45, "dur": 0.1},
            {"step": 3.0,  "pitch": 38, "vel": 0.88, "dur": 0.1},
            {"step": 3.5,  "pitch": 38, "vel": 0.20, "dur": 0.1},
        ],
    },
    {
        "id": "dnb_hihat_16th_a",
        "genre": "drum and bass",
        "role": "hihat",
        "length_beats": 4.0,
        "description": "DnB Hi-Hat — 16tel-Noten, Akzente auf 8tel",
        "notes": [
            {"step": 0.0,  "pitch": 42, "vel": 0.65, "dur": 0.1},
            {"step": 0.25, "pitch": 42, "vel": 0.32, "dur": 0.1},
            {"step": 0.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 0.75, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 1.0,  "pitch": 42, "vel": 0.65, "dur": 0.1},
            {"step": 1.25, "pitch": 42, "vel": 0.32, "dur": 0.1},
            {"step": 1.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 1.75, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 2.0,  "pitch": 42, "vel": 0.65, "dur": 0.1},
            {"step": 2.25, "pitch": 42, "vel": 0.32, "dur": 0.1},
            {"step": 2.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 2.75, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 3.0,  "pitch": 42, "vel": 0.65, "dur": 0.1},
            {"step": 3.25, "pitch": 42, "vel": 0.32, "dur": 0.1},
            {"step": 3.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 3.75, "pitch": 42, "vel": 0.28, "dur": 0.1},
        ],
    },
    {
        "id": "dnb_hihat_roll_b",
        "genre": "drum and bass",
        "role": "hihat",
        "length_beats": 4.0,
        "description": "DnB Hi-Hat — Roll-Variante mit 32stel-Fills",
        "notes": [
            {"step": 0.0,   "pitch": 42, "vel": 0.68, "dur": 0.1},
            {"step": 0.25,  "pitch": 42, "vel": 0.30, "dur": 0.1},
            {"step": 0.5,   "pitch": 42, "vel": 0.58, "dur": 0.1},
            {"step": 0.75,  "pitch": 42, "vel": 0.25, "dur": 0.1},
            {"step": 1.0,   "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 1.25,  "pitch": 42, "vel": 0.35, "dur": 0.1},
            {"step": 1.5,   "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 1.625, "pitch": 42, "vel": 0.28, "dur": 0.1},  # 32nd roll
            {"step": 1.75,  "pitch": 42, "vel": 0.40, "dur": 0.1},
            {"step": 1.875, "pitch": 42, "vel": 0.22, "dur": 0.1},  # 32nd roll
            {"step": 2.0,   "pitch": 42, "vel": 0.65, "dur": 0.1},
            {"step": 2.25,  "pitch": 42, "vel": 0.30, "dur": 0.1},
            {"step": 2.5,   "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 2.75,  "pitch": 42, "vel": 0.25, "dur": 0.1},
            {"step": 3.0,   "pitch": 42, "vel": 0.68, "dur": 0.1},
            {"step": 3.25,  "pitch": 42, "vel": 0.32, "dur": 0.1},
            {"step": 3.5,   "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 3.625, "pitch": 42, "vel": 0.28, "dur": 0.1},  # 32nd roll
            {"step": 3.75,  "pitch": 42, "vel": 0.40, "dur": 0.1},
            {"step": 3.875, "pitch": 42, "vel": 0.22, "dur": 0.1},  # 32nd roll
        ],
    },

    # ── DUBSTEP ───────────────────────────────────────────────────────────────
    # Charakteristik: Half-Time-Feel, Snare auf Beat 3 (step 4.0 in 8-Beat-Pattern),
    #                 schwere Kicks, sparse Hats

    {
        "id": "dubstep_kick_halftime_a",
        "genre": "dubstep",
        "role": "kick",
        "length_beats": 8.0,
        "description": "Dubstep Kick — Half-Time Bounce",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.95, "dur": 0.25},
            {"step": 1.0,  "pitch": 36, "vel": 0.68, "dur": 0.25},
            {"step": 2.5,  "pitch": 36, "vel": 0.80, "dur": 0.25},
            {"step": 4.0,  "pitch": 36, "vel": 0.90, "dur": 0.25},
            {"step": 5.0,  "pitch": 36, "vel": 0.65, "dur": 0.25},
            {"step": 6.5,  "pitch": 36, "vel": 0.75, "dur": 0.25},
            {"step": 7.0,  "pitch": 36, "vel": 0.70, "dur": 0.25},
        ],
    },
    {
        "id": "dubstep_kick_halftime_b",
        "genre": "dubstep",
        "role": "kick",
        "length_beats": 8.0,
        "description": "Dubstep Kick — Half-Time Heavy",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.96, "dur": 0.25},
            {"step": 2.0,  "pitch": 36, "vel": 0.82, "dur": 0.25},
            {"step": 3.5,  "pitch": 36, "vel": 0.72, "dur": 0.25},
            {"step": 4.0,  "pitch": 36, "vel": 0.90, "dur": 0.25},
            {"step": 6.0,  "pitch": 36, "vel": 0.75, "dur": 0.25},
            {"step": 7.0,  "pitch": 36, "vel": 0.68, "dur": 0.25},
            {"step": 7.5,  "pitch": 36, "vel": 0.60, "dur": 0.25},
        ],
    },
    {
        "id": "dubstep_snare_halftime_a",
        "genre": "dubstep",
        "role": "snare",
        "length_beats": 8.0,
        "description": "Dubstep Snare — Big Half-Time Hit auf Beat 3",
        "notes": [
            {"step": 1.5,  "pitch": 38, "vel": 0.32, "dur": 0.1},  # ghost
            {"step": 2.5,  "pitch": 38, "vel": 0.28, "dur": 0.1},  # ghost
            {"step": 4.0,  "pitch": 38, "vel": 0.96, "dur": 0.1},  # main hit
            {"step": 6.0,  "pitch": 38, "vel": 0.28, "dur": 0.1},  # ghost
            {"step": 7.5,  "pitch": 38, "vel": 0.25, "dur": 0.1},  # ghost
        ],
    },
    {
        "id": "dubstep_hihat_sparse_a",
        "genre": "dubstep",
        "role": "hihat",
        "length_beats": 8.0,
        "description": "Dubstep Hi-Hat — Sparse 8tel",
        "notes": [
            {"step": 0.0,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 2.0,  "pitch": 42, "vel": 0.48, "dur": 0.1},
            {"step": 4.0,  "pitch": 42, "vel": 0.52, "dur": 0.1},
            {"step": 6.0,  "pitch": 42, "vel": 0.45, "dur": 0.1},
        ],
    },

    # ── HOUSE ─────────────────────────────────────────────────────────────────
    # Charakteristik: 4-on-the-Floor Kick, Clap auf 2&4,
    #                 Off-Beat Hi-Hats mit Open-Hat-Feeling

    {
        "id": "house_kick_4floor_a",
        "genre": "house",
        "role": "kick",
        "length_beats": 4.0,
        "description": "House Kick — 4-on-the-Floor Classic",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
            {"step": 1.0,  "pitch": 36, "vel": 0.88, "dur": 0.25},
            {"step": 2.0,  "pitch": 36, "vel": 0.90, "dur": 0.25},
            {"step": 3.0,  "pitch": 36, "vel": 0.88, "dur": 0.25},
        ],
    },
    {
        "id": "house_snare_backbeat_a",
        "genre": "house",
        "role": "snare",
        "length_beats": 4.0,
        "description": "House Snare — Backbeat 2&4",
        "notes": [
            {"step": 1.0,  "pitch": 38, "vel": 0.82, "dur": 0.1},
            {"step": 3.0,  "pitch": 38, "vel": 0.85, "dur": 0.1},
        ],
    },
    {
        "id": "house_clap_backbeat_a",
        "genre": "house",
        "role": "clap",
        "length_beats": 4.0,
        "description": "House Clap — Backbeat 2&4 mit leichtem Verb-Tail-Echo",
        "notes": [
            {"step": 1.0,  "pitch": 39, "vel": 0.85, "dur": 0.1},
            {"step": 1.5,  "pitch": 39, "vel": 0.22, "dur": 0.1},  # echo ghost
            {"step": 3.0,  "pitch": 39, "vel": 0.88, "dur": 0.1},
            {"step": 3.5,  "pitch": 39, "vel": 0.20, "dur": 0.1},  # echo ghost
        ],
    },
    {
        "id": "house_hihat_offbeat_a",
        "genre": "house",
        "role": "hihat",
        "length_beats": 4.0,
        "description": "House Hi-Hat — Off-Beat Akzente (Chicago-Style)",
        "notes": [
            {"step": 0.0,  "pitch": 42, "vel": 0.45, "dur": 0.1},
            {"step": 0.5,  "pitch": 42, "vel": 0.68, "dur": 0.1},
            {"step": 1.0,  "pitch": 42, "vel": 0.45, "dur": 0.1},
            {"step": 1.5,  "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 2.0,  "pitch": 42, "vel": 0.45, "dur": 0.1},
            {"step": 2.5,  "pitch": 42, "vel": 0.68, "dur": 0.1},
            {"step": 3.0,  "pitch": 42, "vel": 0.45, "dur": 0.1},
            {"step": 3.5,  "pitch": 42, "vel": 0.72, "dur": 0.1},
        ],
    },
    {
        "id": "house_hihat_16th_b",
        "genre": "house",
        "role": "hihat",
        "length_beats": 4.0,
        "description": "House Hi-Hat — 16tel für energetische Sets",
        "notes": [
            {"step": 0.0,  "pitch": 42, "vel": 0.60, "dur": 0.1},
            {"step": 0.25, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 0.5,  "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 0.75, "pitch": 42, "vel": 0.25, "dur": 0.1},
            {"step": 1.0,  "pitch": 42, "vel": 0.60, "dur": 0.1},
            {"step": 1.25, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 1.5,  "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 1.75, "pitch": 42, "vel": 0.25, "dur": 0.1},
            {"step": 2.0,  "pitch": 42, "vel": 0.60, "dur": 0.1},
            {"step": 2.25, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 2.5,  "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 2.75, "pitch": 42, "vel": 0.25, "dur": 0.1},
            {"step": 3.0,  "pitch": 42, "vel": 0.60, "dur": 0.1},
            {"step": 3.25, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 3.5,  "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 3.75, "pitch": 42, "vel": 0.25, "dur": 0.1},
        ],
    },

    # ── TECHNO ────────────────────────────────────────────────────────────────
    # Charakteristik: eisenharter 4-on-the-Floor, Propulsion durch Ghost-Kicks,
    #                 hypnotische 16tel-Hats

    {
        "id": "techno_kick_propulsion_a",
        "genre": "techno",
        "role": "kick",
        "length_beats": 4.0,
        "description": "Techno Kick — 4-on-the-Floor mit Ghost-Propulsion",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.96, "dur": 0.25},
            {"step": 0.75, "pitch": 36, "vel": 0.30, "dur": 0.1},   # ghost → propulsion
            {"step": 1.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
            {"step": 1.75, "pitch": 36, "vel": 0.28, "dur": 0.1},
            {"step": 2.0,  "pitch": 36, "vel": 0.96, "dur": 0.25},
            {"step": 2.75, "pitch": 36, "vel": 0.30, "dur": 0.1},
            {"step": 3.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
            {"step": 3.75, "pitch": 36, "vel": 0.35, "dur": 0.1},
        ],
    },
    {
        "id": "techno_kick_clean_b",
        "genre": "techno",
        "role": "kick",
        "length_beats": 4.0,
        "description": "Techno Kick — 4-on-the-Floor Clean, minimal",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.95, "dur": 0.25},
            {"step": 1.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
            {"step": 2.0,  "pitch": 36, "vel": 0.95, "dur": 0.25},
            {"step": 3.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
        ],
    },
    {
        "id": "techno_snare_sparse_a",
        "genre": "techno",
        "role": "snare",
        "length_beats": 4.0,
        "description": "Techno Snare — Minimal Clap auf 2&4",
        "notes": [
            {"step": 1.0,  "pitch": 38, "vel": 0.78, "dur": 0.1},
            {"step": 3.0,  "pitch": 38, "vel": 0.82, "dur": 0.1},
        ],
    },
    {
        "id": "techno_hihat_16th_a",
        "genre": "techno",
        "role": "hihat",
        "length_beats": 4.0,
        "description": "Techno Hi-Hat — 16tel-Hypnose",
        "notes": [
            {"step": 0.0,  "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 0.25, "pitch": 42, "vel": 0.32, "dur": 0.1},
            {"step": 0.5,  "pitch": 42, "vel": 0.52, "dur": 0.1},
            {"step": 0.75, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 1.0,  "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 1.25, "pitch": 42, "vel": 0.32, "dur": 0.1},
            {"step": 1.5,  "pitch": 42, "vel": 0.52, "dur": 0.1},
            {"step": 1.75, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 2.0,  "pitch": 42, "vel": 0.72, "dur": 0.1},
            {"step": 2.25, "pitch": 42, "vel": 0.30, "dur": 0.1},
            {"step": 2.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 2.75, "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 3.0,  "pitch": 42, "vel": 0.70, "dur": 0.1},
            {"step": 3.25, "pitch": 42, "vel": 0.32, "dur": 0.1},
            {"step": 3.5,  "pitch": 42, "vel": 0.52, "dur": 0.1},
            {"step": 3.75, "pitch": 42, "vel": 0.28, "dur": 0.1},
        ],
    },
    {
        "id": "techno_hihat_8th_b",
        "genre": "techno",
        "role": "hihat",
        "length_beats": 4.0,
        "description": "Techno Hi-Hat — 8tel, treibend",
        "notes": [
            {"step": 0.0,  "pitch": 42, "vel": 0.72, "dur": 0.1},
            {"step": 0.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 1.0,  "pitch": 42, "vel": 0.72, "dur": 0.1},
            {"step": 1.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 2.0,  "pitch": 42, "vel": 0.72, "dur": 0.1},
            {"step": 2.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 3.0,  "pitch": 42, "vel": 0.72, "dur": 0.1},
            {"step": 3.5,  "pitch": 42, "vel": 0.55, "dur": 0.1},
        ],
    },

    # ── TRAP ──────────────────────────────────────────────────────────────────
    # Charakteristik: langsamer komplexer Kick, Clap auf halbe Zeit,
    #                 Maschinengewehr-Hi-Hat-Rolls

    {
        "id": "trap_kick_complex_a",
        "genre": "trap",
        "role": "kick",
        "length_beats": 8.0,
        "description": "Trap Kick — Komplex, Half-Time-Feel",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
            {"step": 1.5,  "pitch": 36, "vel": 0.72, "dur": 0.25},
            {"step": 2.0,  "pitch": 36, "vel": 0.85, "dur": 0.25},
            {"step": 2.75, "pitch": 36, "vel": 0.65, "dur": 0.25},
            {"step": 4.0,  "pitch": 36, "vel": 0.90, "dur": 0.25},
            {"step": 5.0,  "pitch": 36, "vel": 0.70, "dur": 0.25},
            {"step": 6.0,  "pitch": 36, "vel": 0.85, "dur": 0.25},
            {"step": 7.5,  "pitch": 36, "vel": 0.75, "dur": 0.25},
        ],
    },
    {
        "id": "trap_kick_sparse_b",
        "genre": "trap",
        "role": "kick",
        "length_beats": 8.0,
        "description": "Trap Kick — Sparse, druckvoll",
        "notes": [
            {"step": 0.0,  "pitch": 36, "vel": 0.95, "dur": 0.25},
            {"step": 2.0,  "pitch": 36, "vel": 0.80, "dur": 0.25},
            {"step": 3.5,  "pitch": 36, "vel": 0.68, "dur": 0.25},
            {"step": 4.0,  "pitch": 36, "vel": 0.92, "dur": 0.25},
            {"step": 5.5,  "pitch": 36, "vel": 0.72, "dur": 0.25},
            {"step": 7.0,  "pitch": 36, "vel": 0.78, "dur": 0.25},
        ],
    },
    {
        "id": "trap_snare_halftime_a",
        "genre": "trap",
        "role": "snare",
        "length_beats": 8.0,
        "description": "Trap Snare — Half-Time Backbeat mit Rims",
        "notes": [
            {"step": 1.0,  "pitch": 38, "vel": 0.35, "dur": 0.1},  # rim ghost
            {"step": 2.5,  "pitch": 38, "vel": 0.38, "dur": 0.1},  # rim ghost
            {"step": 4.0,  "pitch": 38, "vel": 0.90, "dur": 0.1},  # main snare
            {"step": 5.0,  "pitch": 38, "vel": 0.30, "dur": 0.1},  # ghost
            {"step": 6.5,  "pitch": 38, "vel": 0.28, "dur": 0.1},  # ghost
        ],
    },
    {
        "id": "trap_clap_halftime_a",
        "genre": "trap",
        "role": "clap",
        "length_beats": 8.0,
        "description": "Trap Clap — Big Reverb Clap auf Beat 3",
        "notes": [
            {"step": 4.0,  "pitch": 39, "vel": 0.92, "dur": 0.1},
            {"step": 4.25, "pitch": 39, "vel": 0.28, "dur": 0.1},  # slap echo
        ],
    },
    {
        "id": "trap_hihat_roll_a",
        "genre": "trap",
        "role": "hihat",
        "length_beats": 8.0,
        "description": "Trap Hi-Hat — Maschinengewehr-Rolls (32tel-Bursts)",
        "notes": [
            # Burst 1 (fading in)
            {"step": 0.0,   "pitch": 42, "vel": 0.65, "dur": 0.1},
            {"step": 0.125, "pitch": 42, "vel": 0.45, "dur": 0.1},
            {"step": 0.25,  "pitch": 42, "vel": 0.30, "dur": 0.1},
            # normale 8tel
            {"step": 0.5,   "pitch": 42, "vel": 0.58, "dur": 0.1},
            {"step": 1.0,   "pitch": 42, "vel": 0.62, "dur": 0.1},
            # Burst 2
            {"step": 1.5,   "pitch": 42, "vel": 0.60, "dur": 0.1},
            {"step": 1.625, "pitch": 42, "vel": 0.42, "dur": 0.1},
            {"step": 1.75,  "pitch": 42, "vel": 0.28, "dur": 0.1},
            {"step": 2.0,   "pitch": 42, "vel": 0.65, "dur": 0.1},
            {"step": 2.125, "pitch": 42, "vel": 0.50, "dur": 0.1},
            {"step": 2.25,  "pitch": 42, "vel": 0.35, "dur": 0.1},
            {"step": 2.375, "pitch": 42, "vel": 0.25, "dur": 0.1},
            {"step": 2.5,   "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 3.0,   "pitch": 42, "vel": 0.68, "dur": 0.1},
            {"step": 3.125, "pitch": 42, "vel": 0.48, "dur": 0.1},
            {"step": 3.25,  "pitch": 42, "vel": 0.35, "dur": 0.1},
            {"step": 3.375, "pitch": 42, "vel": 0.22, "dur": 0.1},
            {"step": 3.5,   "pitch": 42, "vel": 0.45, "dur": 0.1},
            {"step": 3.75,  "pitch": 42, "vel": 0.35, "dur": 0.1},
            # Second half
            {"step": 4.0,   "pitch": 42, "vel": 0.65, "dur": 0.1},
            {"step": 4.5,   "pitch": 42, "vel": 0.55, "dur": 0.1},
            {"step": 5.0,   "pitch": 42, "vel": 0.62, "dur": 0.1},
            {"step": 5.5,   "pitch": 42, "vel": 0.50, "dur": 0.1},
            # Burst 3 (pre-drop)
            {"step": 6.0,   "pitch": 42, "vel": 0.68, "dur": 0.1},
            {"step": 6.125, "pitch": 42, "vel": 0.50, "dur": 0.1},
            {"step": 6.25,  "pitch": 42, "vel": 0.35, "dur": 0.1},
            {"step": 6.5,   "pitch": 42, "vel": 0.58, "dur": 0.1},
            {"step": 6.75,  "pitch": 42, "vel": 0.38, "dur": 0.1},
            {"step": 7.0,   "pitch": 42, "vel": 0.62, "dur": 0.1},
            {"step": 7.5,   "pitch": 42, "vel": 0.52, "dur": 0.1},
        ],
    },
    {
        "id": "trap_hihat_8th_b",
        "genre": "trap",
        "role": "hihat",
        "length_beats": 8.0,
        "description": "Trap Hi-Hat — 8tel, straightforward",
        "notes": [
            {"step": s, "pitch": 42,
             "vel": 0.68 if s % 1.0 == 0.0 else 0.45,
             "dur": 0.1}
            for s in [i * 0.5 for i in range(16)]
        ],
    },
]


# ── Ingestion ──────────────────────────────────────────────────────────────────

def run() -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session, is_available

    if not is_available():
        print("Neo4j nicht erreichbar — abgebrochen.")
        sys.exit(1)

    with neo4j_session() as s:
        for p in PATTERNS:
            notes_json = json.dumps(p["notes"], ensure_ascii=False)
            s.run(
                """
                MERGE (p:Pattern {id: $id})
                SET p.genre        = $genre,
                    p.role         = $role,
                    p.length_beats = $length_beats,
                    p.description  = $description,
                    p.notes_json   = $notes_json
                """,
                id=p["id"],
                genre=p["genre"],
                role=p["role"],
                length_beats=float(p["length_beats"]),
                description=p["description"],
                notes_json=notes_json,
            )
            print(f"  OK  {p['id']} ({len(p['notes'])} Noten)")

    print(f"\n{len(PATTERNS)} Pattern(s) in Neo4j gespeichert.")


if __name__ == "__main__":
    run()
