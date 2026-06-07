"""
Pattern-Generatoren für alle Instrument-Typen und Genres.
"""
from __future__ import annotations
from src.agent.tools.music_data import _CHORDS, _SCALES, _NOTE_NAMES, _DEFAULT_PROGRESSIONS, _root_midi  # noqa: F401

def _drums(genre: str, bars: int, style: str) -> list[dict]:
    notes: list[dict] = []

    def n(step, pitch, vel, dur=0.25):
        notes.append({"step": step, "pitch": pitch, "vel": round(vel, 2), "dur": dur})

    KICK, SNARE, HH_C, HH_O, RIDE = 36, 38, 42, 46, 51

    for bar in range(bars):
        o = bar * 4.0

        if genre == "rock":
            n(o+0.0, KICK,  0.90); n(o+2.0, KICK,  0.85)
            n(o+1.0, SNARE, 0.85); n(o+3.0, SNARE, 0.80)
            if style == "full":
                n(o+3.5, KICK, 0.55)
            for i in range(8):
                n(o+i*0.5, HH_C, 0.65 if i % 2 == 0 else 0.42)

        elif genre in ("hip-hop", "hiphop"):
            n(o+0.0, KICK,  0.95); n(o+1.5, KICK,  0.70); n(o+2.5, KICK, 0.75)
            n(o+1.0, SNARE, 0.90); n(o+3.0, SNARE, 0.85)
            for i in range(16):
                n(o+i*0.25, HH_C, 0.55 if i % 4 == 0 else 0.32)

        elif genre == "trap":
            n(o+0.0,  KICK,  0.95); n(o+0.75, KICK, 0.55)
            n(o+2.0,  KICK,  0.90); n(o+2.5,  KICK, 0.60)
            n(o+1.0,  SNARE, 0.95); n(o+3.0,  SNARE, 0.90)
            for i in range(16):
                n(o+i*0.25, HH_C, 0.72 if i % 4 == 0 else 0.38, 0.125)
            n(o+1.5, HH_O, 0.55, 0.5); n(o+3.5, HH_O, 0.50, 0.5)

        elif genre == "jazz":
            # Ride ist der Hauptrhythmus im Jazz (Swing-Pattern)
            for i in range(4):
                n(o+i,      RIDE, 0.78)       # Beat 1 2 3 4
                n(o+i+0.67, RIDE, 0.50)       # Swing-Triolen-Feeling
            n(o+1.0, SNARE, 0.55)             # Snare auf 2 (Ghost-Note / Brush)
            n(o+3.0, SNARE, 0.60)             # Snare auf 4 (etwas lauter)
            n(o+1.0, 44,    0.65)             # HH-Pedal auf 2 (typisch Jazz)
            n(o+3.0, 44,    0.65)             # HH-Pedal auf 4
            if bar == 0:
                n(o+0.0, KICK, 0.55)          # Kick sparsam, nur 1x pro 2 Takte

        elif genre in ("dnb", "drum and bass"):
            n(o+0.0, KICK,  0.90); n(o+1.5, KICK,  0.72); n(o+3.0, KICK,  0.68)
            n(o+1.0, SNARE, 0.95); n(o+3.5, SNARE, 0.78)
            for i in range(16):
                n(o+i*0.25, HH_C, 0.58 if i % 4 == 0 else 0.32, 0.125)

        elif genre == "funk":
            n(o+0.0, KICK,  0.90); n(o+0.5,  KICK, 0.52)
            n(o+2.0, KICK,  0.80); n(o+2.75, KICK, 0.48); n(o+3.5, KICK, 0.55)
            n(o+1.0, SNARE, 0.85); n(o+2.5,  SNARE, 0.58); n(o+3.0, SNARE, 0.72)
            for i in range(16):
                n(o+i*0.25, HH_C, 0.62 if i % 2 == 0 else 0.38, 0.125)

        else:  # pop / default
            n(o+0.0, KICK,  0.90); n(o+2.0, KICK,  0.85)
            n(o+1.0, SNARE, 0.85); n(o+3.0, SNARE, 0.80)
            for i in range(8):
                n(o+i*0.5, HH_C, 0.55 if i % 2 == 0 else 0.38)

    return notes


def _bass(genre: str, bars: int, root: int, style: str) -> list[dict]:
    notes: list[dict] = []

    def n(step, pitch, vel, dur):
        notes.append({"step": step, "pitch": pitch, "vel": round(vel, 2), "dur": dur})

    r = root
    fifth = r + 7

    for bar in range(bars):
        o = bar * 4.0

        if genre == "rock":
            n(o+0.0, r,     0.85, 1.0); n(o+2.0, r,     0.80, 0.75); n(o+3.0, fifth, 0.68, 0.5)

        elif genre in ("hip-hop", "hiphop", "trap"):
            n(o+0.0, r,   0.90, 0.5); n(o+1.5, r,   0.72, 0.5)
            n(o+2.5, r-2, 0.78, 0.5); n(o+3.5, r,   0.68, 0.5)

        elif genre == "funk":
            n(o+0.0,  r,       0.90, 0.25); n(o+0.5,  r,       0.52, 0.25)
            n(o+0.75, r+2,     0.48, 0.25); n(o+1.0,  r,       0.82, 0.50)
            n(o+2.0,  fifth-12,0.78, 0.25); n(o+2.5,  r,       0.72, 0.50)
            n(o+3.0,  r,       0.75, 0.25); n(o+3.5,  r+5,     0.62, 0.25)

        elif genre == "jazz":
            scale = [0, 2, 4, 5, 7, 9, 10]
            for beat in range(4):
                n(o+beat, r + scale[(bar * 4 + beat) % len(scale)], 0.72, 0.85)

        elif genre in ("dnb", "drum and bass"):
            n(o+0.0,  r,    0.90, 0.5); n(o+0.75, r-2,  0.68, 0.25)
            n(o+1.5,  r,    0.85, 0.5); n(o+2.0,  r+5,  0.72, 0.5); n(o+3.0, r, 0.80, 0.75)

        else:
            n(o+0.0, r,     0.85, 2.0); n(o+2.0, fifth, 0.80, 2.0)

    return notes


def _chords(genre: str, bars: int, chord_list: list[str], style: str) -> list[dict]:
    notes: list[dict] = []
    total_beats = bars * 4
    beats_per_chord = total_beats / max(len(chord_list), 1)

    for ci, chord_name in enumerate(chord_list):
        o = ci * beats_per_chord
        chord_notes = _CHORDS.get(chord_name, [60, 64, 67])

        if style == "arpeggio":
            step_size = 0.25
            for s in range(int(beats_per_chord / step_size)):
                notes.append({"step": o + s * step_size,
                               "pitch": chord_notes[s % len(chord_notes)],
                               "vel": round(0.72 if s % 4 == 0 else 0.55, 2), "dur": 0.2})
        elif style == "staccato":
            for beat in range(0, int(beats_per_chord), 2):
                for pitch in chord_notes:
                    notes.append({"step": o + beat, "pitch": pitch, "vel": 0.80, "dur": 0.25})
        elif style == "sustained":
            for pitch in chord_notes:
                notes.append({"step": o, "pitch": pitch, "vel": 0.68, "dur": beats_per_chord - 0.1})
        else:
            dur = beats_per_chord / 2 - 0.1
            for rep in range(2):
                for pitch in chord_notes:
                    notes.append({"step": o + rep * (beats_per_chord / 2),
                                   "pitch": pitch, "vel": 0.72, "dur": dur})

    return notes


def _melody(genre: str, bars: int, root: int, scale_name: str, style: str) -> list[dict]:
    notes: list[dict] = []
    scale = _SCALES.get(scale_name, _SCALES["major"])
    scale_notes = [root + i + oct * 12 for oct in range(2) for i in scale
                   if 40 <= root + i + oct * 12 <= 84]

    if not scale_notes:
        scale_notes = [60]

    def idx(n): return scale_notes[n % len(scale_notes)]

    for bar in range(bars):
        o = bar * 4.0
        if genre == "rock":
            for i, d in enumerate([0, 2, 4, 2, 3, 5, 4, 2]):
                notes.append({"step": o + i * 0.5, "pitch": idx(d),
                               "vel": round(0.78 if i % 2 == 0 else 0.60, 2), "dur": 0.4})
        elif genre == "jazz":
            for i in range(8):
                notes.append({"step": o + i * 0.5,
                               "pitch": scale_notes[(bar * 3 + i) % len(scale_notes)],
                               "vel": round(0.72 + 0.12 * (i % 2 == 0), 2), "dur": 0.4})
        elif genre in ("hip-hop", "hiphop", "trap"):
            for i, d in enumerate([0, 0, 3, 2, 4, 3, 5, 5]):
                if i % 3 != 2:
                    notes.append({"step": o + i * 0.5, "pitch": idx(d),
                                   "vel": round(0.75 if i % 2 == 0 else 0.55, 2), "dur": 0.4})
        else:
            for i, d in enumerate([0, 2, 4, 3, 2, 0, 4, 2]):
                notes.append({"step": o + i * 0.5, "pitch": idx(d),
                               "vel": round(0.72 if i % 2 == 0 else 0.58, 2), "dur": 0.4})

    return notes


def _808_kick(genre: str, bars: int) -> list[dict]:
    notes: list[dict] = []
    for bar in range(bars):
        o = bar * 4.0
        hits = [(0.0, 0.95), (0.75, 0.60), (2.0, 0.90), (2.5, 0.55)] if genre == "trap" \
               else [(0.0, 0.92), (1.5, 0.68), (2.5, 0.72)]
        for step, vel in hits:
            notes.append({"step": o + step, "pitch": 36, "vel": round(vel, 2), "dur": 0.5})
    return notes


def _808_snare(genre: str, bars: int) -> list[dict]:
    notes: list[dict] = []
    for bar in range(bars):
        o = bar * 4.0
        for beat in [1.0, 3.0]:
            notes.append({"step": o + beat, "pitch": 38, "vel": 0.92, "dur": 0.25})
        if genre == "trap":
            notes.append({"step": o + 1.5, "pitch": 38, "vel": 0.55, "dur": 0.25})
            notes.append({"step": o + 3.5, "pitch": 38, "vel": 0.52, "dur": 0.25})
    return notes


