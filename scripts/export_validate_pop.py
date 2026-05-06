#!/usr/bin/env python3
"""
Exportiert das Pop-Song-Projekt als MIDI und validiert die musikalische Struktur.
Tracks: Drums(1) | Bass(2) | Chords(3) | Lead(4)
Slots:  Slot 0 = Verse | Slot 1 = Chorus
Song:   Verse×2 → Chorus×2 → Verse×1 → Chorus×2
"""

import sys
import json
from pathlib import Path

import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage

# ── Konstanten ────────────────────────────────────────────────────────────────

BPM          = 100
PPQ          = 480            # ticks per beat
STEP_SIZE    = 0.25           # beats per step (1/16 note)
CLIP_BEATS   = 8.0            # 2 bars per clip
OUT_DIR      = Path("/home/sija/bitwig-agent/scripts/output")
MIDI_OUT     = OUT_DIR / "pop_song.mid"
REPORT_OUT   = OUT_DIR / "pop_song_validation.json"

# ── Patterns (beat-space, identisch mit MCP-Aufrufen) ────────────────────────

VERSE_DRUMS = [
    {"step":0,   "pitch":36, "vel":0.9,  "dur":0.25},
    {"step":2,   "pitch":36, "vel":0.85, "dur":0.25},
    {"step":4,   "pitch":36, "vel":0.9,  "dur":0.25},
    {"step":6,   "pitch":36, "vel":0.85, "dur":0.25},
    {"step":1,   "pitch":38, "vel":0.8,  "dur":0.25},
    {"step":3,   "pitch":38, "vel":0.8,  "dur":0.25},
    {"step":5,   "pitch":38, "vel":0.8,  "dur":0.25},
    {"step":7,   "pitch":38, "vel":0.8,  "dur":0.25},
    {"step":0,   "pitch":42, "vel":0.55, "dur":0.1},
    {"step":0.5, "pitch":42, "vel":0.45, "dur":0.1},
    {"step":1,   "pitch":42, "vel":0.55, "dur":0.1},
    {"step":1.5, "pitch":42, "vel":0.45, "dur":0.1},
    {"step":2,   "pitch":42, "vel":0.55, "dur":0.1},
    {"step":2.5, "pitch":42, "vel":0.45, "dur":0.1},
    {"step":3,   "pitch":42, "vel":0.55, "dur":0.1},
    {"step":3.5, "pitch":42, "vel":0.45, "dur":0.1},
    {"step":4,   "pitch":42, "vel":0.55, "dur":0.1},
    {"step":4.5, "pitch":42, "vel":0.45, "dur":0.1},
    {"step":5,   "pitch":42, "vel":0.55, "dur":0.1},
    {"step":5.5, "pitch":42, "vel":0.45, "dur":0.1},
    {"step":6,   "pitch":42, "vel":0.55, "dur":0.1},
    {"step":6.5, "pitch":42, "vel":0.45, "dur":0.1},
    {"step":7,   "pitch":42, "vel":0.55, "dur":0.1},
    {"step":7.5, "pitch":42, "vel":0.45, "dur":0.1},
]

CHORUS_DRUMS = [
    {"step":0,   "pitch":36, "vel":0.95, "dur":0.25},
    {"step":2,   "pitch":36, "vel":0.9,  "dur":0.25},
    {"step":3.5, "pitch":36, "vel":0.8,  "dur":0.25},
    {"step":4,   "pitch":36, "vel":0.95, "dur":0.25},
    {"step":6,   "pitch":36, "vel":0.9,  "dur":0.25},
    {"step":7.5, "pitch":36, "vel":0.8,  "dur":0.25},
    {"step":1,   "pitch":38, "vel":0.9,  "dur":0.25},
    {"step":3,   "pitch":38, "vel":0.9,  "dur":0.25},
    {"step":5,   "pitch":38, "vel":0.95, "dur":0.25},
    {"step":7,   "pitch":38, "vel":0.9,  "dur":0.25},
    {"step":0,   "pitch":42, "vel":0.6,  "dur":0.1},
    {"step":0.5, "pitch":42, "vel":0.5,  "dur":0.1},
    {"step":1,   "pitch":42, "vel":0.6,  "dur":0.1},
    {"step":1.5, "pitch":42, "vel":0.5,  "dur":0.1},
    {"step":2,   "pitch":42, "vel":0.6,  "dur":0.1},
    {"step":2.5, "pitch":42, "vel":0.5,  "dur":0.1},
    {"step":3,   "pitch":42, "vel":0.6,  "dur":0.1},
    {"step":3.5, "pitch":46, "vel":0.7,  "dur":0.3},
    {"step":4,   "pitch":42, "vel":0.6,  "dur":0.1},
    {"step":4.5, "pitch":42, "vel":0.5,  "dur":0.1},
    {"step":5,   "pitch":42, "vel":0.6,  "dur":0.1},
    {"step":5.5, "pitch":42, "vel":0.5,  "dur":0.1},
    {"step":6,   "pitch":42, "vel":0.6,  "dur":0.1},
    {"step":6.5, "pitch":42, "vel":0.5,  "dur":0.1},
    {"step":7,   "pitch":42, "vel":0.6,  "dur":0.1},
    {"step":7.5, "pitch":46, "vel":0.7,  "dur":0.3},
]

VERSE_BASS = [
    {"step":0,   "pitch":48, "vel":0.85, "dur":0.75},
    {"step":1,   "pitch":48, "vel":0.7,  "dur":0.25},
    {"step":1.5, "pitch":50, "vel":0.65, "dur":0.25},
    {"step":2,   "pitch":45, "vel":0.85, "dur":0.75},
    {"step":3,   "pitch":45, "vel":0.7,  "dur":0.25},
    {"step":3.5, "pitch":47, "vel":0.6,  "dur":0.25},
    {"step":4,   "pitch":41, "vel":0.85, "dur":0.75},
    {"step":5,   "pitch":41, "vel":0.7,  "dur":0.25},
    {"step":5.5, "pitch":43, "vel":0.6,  "dur":0.25},
    {"step":6,   "pitch":43, "vel":0.85, "dur":0.75},
    {"step":7,   "pitch":43, "vel":0.7,  "dur":0.5},
]

CHORUS_BASS = [
    {"step":0,   "pitch":48, "vel":0.9,  "dur":0.5},
    {"step":0.5, "pitch":60, "vel":0.75, "dur":0.25},
    {"step":1,   "pitch":48, "vel":0.85, "dur":0.5},
    {"step":1.5, "pitch":50, "vel":0.7,  "dur":0.25},
    {"step":2,   "pitch":45, "vel":0.9,  "dur":0.5},
    {"step":2.5, "pitch":57, "vel":0.75, "dur":0.25},
    {"step":3,   "pitch":45, "vel":0.85, "dur":0.5},
    {"step":3.5, "pitch":47, "vel":0.7,  "dur":0.25},
    {"step":4,   "pitch":41, "vel":0.9,  "dur":0.5},
    {"step":4.5, "pitch":53, "vel":0.75, "dur":0.25},
    {"step":5,   "pitch":41, "vel":0.85, "dur":0.5},
    {"step":5.5, "pitch":43, "vel":0.7,  "dur":0.25},
    {"step":6,   "pitch":43, "vel":0.9,  "dur":0.5},
    {"step":6.5, "pitch":55, "vel":0.75, "dur":0.25},
    {"step":7,   "pitch":43, "vel":0.85, "dur":0.5},
    {"step":7.5, "pitch":45, "vel":0.7,  "dur":0.25},
]

VERSE_CHORDS = [
    {"step":0, "pitch":60, "vel":0.65, "dur":1.9},
    {"step":0, "pitch":64, "vel":0.6,  "dur":1.9},
    {"step":0, "pitch":67, "vel":0.55, "dur":1.9},
    {"step":2, "pitch":57, "vel":0.65, "dur":1.9},
    {"step":2, "pitch":60, "vel":0.6,  "dur":1.9},
    {"step":2, "pitch":64, "vel":0.55, "dur":1.9},
    {"step":4, "pitch":53, "vel":0.65, "dur":1.9},
    {"step":4, "pitch":57, "vel":0.6,  "dur":1.9},
    {"step":4, "pitch":60, "vel":0.55, "dur":1.9},
    {"step":6, "pitch":55, "vel":0.65, "dur":1.9},
    {"step":6, "pitch":59, "vel":0.6,  "dur":1.9},
    {"step":6, "pitch":62, "vel":0.55, "dur":1.9},
]

CHORUS_CHORDS = [
    {"step":0, "pitch":60, "vel":0.8,  "dur":1.9},
    {"step":0, "pitch":64, "vel":0.75, "dur":1.9},
    {"step":0, "pitch":67, "vel":0.7,  "dur":1.9},
    {"step":0, "pitch":72, "vel":0.65, "dur":1.9},
    {"step":2, "pitch":57, "vel":0.8,  "dur":1.9},
    {"step":2, "pitch":60, "vel":0.75, "dur":1.9},
    {"step":2, "pitch":64, "vel":0.7,  "dur":1.9},
    {"step":2, "pitch":69, "vel":0.65, "dur":1.9},
    {"step":4, "pitch":53, "vel":0.8,  "dur":1.9},
    {"step":4, "pitch":57, "vel":0.75, "dur":1.9},
    {"step":4, "pitch":60, "vel":0.7,  "dur":1.9},
    {"step":4, "pitch":65, "vel":0.65, "dur":1.9},
    {"step":6, "pitch":55, "vel":0.8,  "dur":1.9},
    {"step":6, "pitch":59, "vel":0.75, "dur":1.9},
    {"step":6, "pitch":62, "vel":0.7,  "dur":1.9},
    {"step":6, "pitch":67, "vel":0.65, "dur":1.9},
]

VERSE_LEAD = [
    {"step":0,    "pitch":72, "vel":0.75, "dur":0.5},
    {"step":0.5,  "pitch":71, "vel":0.7,  "dur":0.5},
    {"step":1,    "pitch":69, "vel":0.75, "dur":0.75},
    {"step":2,    "pitch":67, "vel":0.7,  "dur":0.5},
    {"step":2.5,  "pitch":69, "vel":0.65, "dur":0.25},
    {"step":3,    "pitch":72, "vel":0.8,  "dur":1.0},
    {"step":4,    "pitch":74, "vel":0.8,  "dur":0.5},
    {"step":4.5,  "pitch":72, "vel":0.75, "dur":0.5},
    {"step":5,    "pitch":69, "vel":0.7,  "dur":0.75},
    {"step":6,    "pitch":67, "vel":0.75, "dur":0.5},
    {"step":6.5,  "pitch":65, "vel":0.65, "dur":0.5},
    {"step":7,    "pitch":64, "vel":0.7,  "dur":0.75},
]

CHORUS_LEAD = [
    {"step":0,    "pitch":79, "vel":0.9,  "dur":0.5},
    {"step":0.5,  "pitch":79, "vel":0.8,  "dur":0.25},
    {"step":0.75, "pitch":77, "vel":0.75, "dur":0.25},
    {"step":1,    "pitch":76, "vel":0.85, "dur":0.75},
    {"step":2,    "pitch":72, "vel":0.8,  "dur":0.5},
    {"step":2.5,  "pitch":74, "vel":0.75, "dur":0.5},
    {"step":3,    "pitch":76, "vel":0.9,  "dur":1.0},
    {"step":4,    "pitch":79, "vel":0.9,  "dur":0.5},
    {"step":4.5,  "pitch":79, "vel":0.8,  "dur":0.25},
    {"step":4.75, "pitch":77, "vel":0.75, "dur":0.25},
    {"step":5,    "pitch":76, "vel":0.85, "dur":0.75},
    {"step":6,    "pitch":74, "vel":0.8,  "dur":0.5},
    {"step":6.5,  "pitch":72, "vel":0.75, "dur":0.5},
    {"step":7,    "pitch":74, "vel":0.85, "dur":1.0},
]

# Song-Struktur: (slot, repeats)
SONG_STRUCTURE = [
    ("verse",  2),
    ("chorus", 2),
    ("verse",  1),
    ("chorus", 2),
]

TRACK_PATTERNS = {
    "drums":  {"verse": VERSE_DRUMS,  "chorus": CHORUS_DRUMS},
    "bass":   {"verse": VERSE_BASS,   "chorus": CHORUS_BASS},
    "chords": {"verse": VERSE_CHORDS, "chorus": CHORUS_CHORDS},
    "lead":   {"verse": VERSE_LEAD,   "chorus": CHORUS_LEAD},
}

TRACK_PROGRAMS = {
    "drums":  (9,  0),   # channel 9 = drums
    "bass":   (0,  33),  # electric bass
    "chords": (0,  81),  # synth lead → pad feel
    "lead":   (0,  80),  # synth lead
}


# ── MIDI-Hilfsfunktionen ──────────────────────────────────────────────────────

def beats_to_ticks(beats: float) -> int:
    return int(round(beats * PPQ))


def build_track_events(name: str) -> list[tuple[int, Message]]:
    """Gibt eine Liste von (abs_tick, Message) zurück."""
    events: list[tuple[int, Message]] = []
    channel, program = TRACK_PROGRAMS[name]

    if channel != 9:
        events.append((0, Message("program_change", channel=channel, program=program, time=0)))

    current_beat = 0.0
    for section, repeats in SONG_STRUCTURE:
        pattern = TRACK_PATTERNS[name][section]
        for _ in range(repeats):
            for n in pattern:
                abs_start = current_beat + n["step"]
                abs_end   = abs_start + n["dur"]
                vel = max(1, min(127, int(round(n["vel"] * 127))))
                events.append((beats_to_ticks(abs_start),
                               Message("note_on",  channel=channel,
                                       note=n["pitch"], velocity=vel, time=0)))
                events.append((beats_to_ticks(abs_end),
                               Message("note_off", channel=channel,
                                       note=n["pitch"], velocity=0, time=0)))
            current_beat += CLIP_BEATS

    return events


def events_to_track(name: str, events: list[tuple[int, Message]]) -> MidiTrack:
    track = MidiTrack()
    track.append(MetaMessage("track_name", name=name, time=0))
    sorted_events = sorted(events, key=lambda e: e[0])
    prev_tick = 0
    for abs_tick, msg in sorted_events:
        delta = abs_tick - prev_tick
        track.append(msg.copy(time=delta))
        prev_tick = abs_tick
    track.append(MetaMessage("end_of_track", time=0))
    return track


# ── Export ────────────────────────────────────────────────────────────────────

def export_midi() -> MidiFile:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mid = MidiFile(type=1, ticks_per_beat=PPQ)

    # Tempo-Track
    tempo_track = MidiTrack()
    tempo_us = int(60_000_000 / BPM)
    tempo_track.append(MetaMessage("set_tempo", tempo=tempo_us, time=0))
    tempo_track.append(MetaMessage("time_signature", numerator=4, denominator=4,
                                   clocks_per_click=24, time=0))
    tempo_track.append(MetaMessage("end_of_track", time=0))
    mid.tracks.append(tempo_track)

    for name in ["drums", "bass", "chords", "lead"]:
        events = build_track_events(name)
        mid.tracks.append(events_to_track(name, events))

    mid.save(str(MIDI_OUT))
    return mid


# ── Validierung ───────────────────────────────────────────────────────────────

CHORD_ROOTS = {
    "C":  [60, 64, 67],
    "Am": [57, 60, 64],
    "F":  [53, 57, 60],
    "G":  [55, 59, 62],
}

VALID_DRUM_PITCHES = {36, 38, 42, 46}
VALID_KEY_PITCHES  = {60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79,
                      41, 43, 45, 47, 48, 50, 53, 55, 57, 59}


def validate_song() -> dict:
    issues  = []
    ok      = []
    details = {}

    total_beats = sum(r * CLIP_BEATS for _, r in SONG_STRUCTURE)

    # ── 1. Drum-Pitches ───────────────────────────────────────────────────────
    drum_pitches = {n["pitch"] for p in TRACK_PATTERNS["drums"].values() for n in p}
    invalid_drums = drum_pitches - VALID_DRUM_PITCHES
    if invalid_drums:
        issues.append(f"Drums: unbekannte Pitches {invalid_drums}")
    else:
        ok.append("Drums: nur Standard-GM-Pitches (Kick/Snare/Hat/OpenHat)")

    # ── 2. Kick/Snare auf richtigen Beats ────────────────────────────────────
    for slot, pattern in TRACK_PATTERNS["drums"].items():
        kicks  = sorted(n["step"] for n in pattern if n["pitch"] == 36)
        snares = sorted(n["step"] for n in pattern if n["pitch"] == 38)
        exp_kicks  = [0, 2, 4, 6]
        exp_snares = [1, 3, 5, 7]
        if not all(k in kicks for k in exp_kicks):
            issues.append(f"Drums/{slot}: Kick fehlt auf Beat(s) {[k for k in exp_kicks if k not in kicks]}")
        else:
            ok.append(f"Drums/{slot}: Kick korrekt auf Beats 1&3 (steps 0,2,4,6)")
        if not all(s in snares for s in exp_snares):
            issues.append(f"Drums/{slot}: Snare fehlt auf Beat(s) {[s for s in exp_snares if s not in snares]}")
        else:
            ok.append(f"Drums/{slot}: Snare korrekt auf Beats 2&4 (steps 1,3,5,7)")

    # ── 3. Hihat-Dichte (mind. 8tel = 16 Hihats pro 8 Beats) ────────────────
    for slot, pattern in TRACK_PATTERNS["drums"].items():
        hihats = [n for n in pattern if n["pitch"] in {42, 46}]
        if len(hihats) < 14:
            issues.append(f"Drums/{slot}: zu wenige Hihats ({len(hihats)}, erwartet ≥14)")
        else:
            ok.append(f"Drums/{slot}: Hihat-Dichte ok ({len(hihats)} Noten)")

    # ── 4. Bass-Roots (C=48/60, Am=45/57, F=41/53, G=43/55) ─────────────────
    expected_roots = {48, 45, 41, 43}
    for slot, pattern in TRACK_PATTERNS["bass"].items():
        roots = {n["pitch"] for n in pattern if n["step"] in {0, 2, 4, 6}}
        missing = expected_roots - roots
        if missing:
            issues.append(f"Bass/{slot}: Grundtöne fehlen auf Beats {missing}")
        else:
            ok.append(f"Bass/{slot}: C/Am/F/G Grundtöne korrekt platziert")

    # ── 5. Chord-Pitches entsprechen C-Am-F-G ────────────────────────────────
    expected_chord_sets = [
        ({60,64,67}, "C"),
        ({57,60,64}, "Am"),
        ({53,57,60}, "F"),
        ({55,59,62}, "G"),
    ]
    for slot, pattern in TRACK_PATTERNS["chords"].items():
        by_step: dict[float, set] = {}
        for n in pattern:
            by_step.setdefault(n["step"], set()).add(n["pitch"])
        chord_steps = sorted(by_step.keys())
        for i, step in enumerate(chord_steps[:4]):
            exp_pitches, chord_name = expected_chord_sets[i % 4]
            actual = by_step[step]
            missing = exp_pitches - actual
            extra   = actual - exp_pitches - {p+12 for p in exp_pitches}
            if missing:
                issues.append(f"Chords/{slot} step {step}: {chord_name} fehlen Töne {missing}")
            else:
                ok.append(f"Chords/{slot} step {step}: {chord_name} korrekt {sorted(actual)}")

    # ── 6. Lead-Melodie im Tonbereich C4–G5 ──────────────────────────────────
    for slot, pattern in TRACK_PATTERNS["lead"].items():
        out_of_range = [n["pitch"] for n in pattern if not (60 <= n["pitch"] <= 81)]
        if out_of_range:
            issues.append(f"Lead/{slot}: Töne außerhalb C4–A5: {out_of_range}")
        else:
            ok.append(f"Lead/{slot}: alle Töne im Bereich C4–A5 ✓")

    # ── 7. Keine Note außerhalb Clip-Länge ────────────────────────────────────
    for name, slots in TRACK_PATTERNS.items():
        for slot, pattern in slots.items():
            overrun = [n for n in pattern if n["step"] + n["dur"] > CLIP_BEATS + 0.01]
            if overrun:
                issues.append(f"{name}/{slot}: {len(overrun)} Noten überschreiten Clip-Ende ({CLIP_BEATS} Beats)")
            else:
                ok.append(f"{name}/{slot}: alle Noten innerhalb Clip-Länge")

    # ── 8. Song-Länge ─────────────────────────────────────────────────────────
    expected_beats = total_beats
    details["song_length_beats"] = expected_beats
    details["song_length_bars"]  = expected_beats / 4
    details["song_length_sec"]   = expected_beats / BPM * 60
    ok.append(f"Song-Länge: {int(expected_beats)} Beats = "
              f"{int(expected_beats/4)} Takte = "
              f"{details['song_length_sec']:.1f}s @ {BPM} BPM")

    # ── 9. Note-Count pro Track ───────────────────────────────────────────────
    total_sections = sum(r for _, r in SONG_STRUCTURE)
    for name, slots in TRACK_PATTERNS.items():
        verse_n  = len(slots["verse"])
        chorus_n = len(slots["chorus"])
        verse_r  = sum(r for s, r in SONG_STRUCTURE if s == "verse")
        chorus_r = sum(r for s, r in SONG_STRUCTURE if s == "chorus")
        total = verse_n * verse_r + chorus_n * chorus_r
        details[f"{name}_total_notes"] = total
        ok.append(f"{name}: {total} Noten total ({verse_n}×{verse_r} verse + {chorus_n}×{chorus_r} chorus)")

    return {
        "status":  "FAIL" if issues else "PASS",
        "issues":  issues,
        "ok":      ok,
        "details": details,
        "midi":    str(MIDI_OUT),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Exportiere MIDI...")
    export_midi()
    print(f"  → {MIDI_OUT}")

    print("\nValidiere Song...")
    report = validate_song()
    report["midi"] = str(MIDI_OUT)

    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    status_icon = "✓" if report["status"] == "PASS" else "✗"
    print(f"\n{status_icon} Status: {report['status']}")

    if report["ok"]:
        print(f"\n✓ OK ({len(report['ok'])} Checks):")
        for msg in report["ok"]:
            print(f"  · {msg}")

    if report["issues"]:
        print(f"\n✗ Probleme ({len(report['issues'])}):")
        for msg in report["issues"]:
            print(f"  ! {msg}")

    print(f"\nDetails:")
    for k, v in report["details"].items():
        print(f"  {k}: {v}")

    print(f"\nReport: {REPORT_OUT}")
    sys.exit(0 if report["status"] == "PASS" else 1)
