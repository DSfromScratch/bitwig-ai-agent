"""
Python-basierte Pattern-Generierung für alle VST- und Bitwig-Instrumente.
Der Agent spezifiziert Genre/Stil, Python berechnet exakte MIDI-Werte.
"""
from __future__ import annotations
from langchain_core.tools import tool

# ── Chord Library ──────────────────────────────────────────────────────────────

_CHORDS: dict[str, list[int]] = {
    "C":      [60, 64, 67],  "Cm":     [60, 63, 67],
    "D":      [62, 66, 69],  "Dm":     [62, 65, 69],
    "E":      [64, 68, 71],  "Em":     [64, 67, 71],
    "F":      [65, 69, 72],  "Fm":     [65, 68, 72],
    "G":      [67, 71, 74],  "Gm":     [67, 70, 74],
    "A":      [69, 73, 76],  "Am":     [57, 60, 64],
    "Bb":     [58, 62, 65],  "Bbm":    [58, 61, 65],
    "B":      [59, 63, 66],  "Bm":     [59, 62, 66],
    "Cmaj7":  [60, 64, 67, 71],  "Dm7":    [62, 65, 69, 72],
    "Em7":    [64, 67, 71, 74],  "Fmaj7":  [65, 69, 72, 76],
    "G7":     [67, 71, 74, 77],  "Am7":    [57, 60, 64, 67],
    "Gmaj7":  [67, 71, 74, 78],  "Cmaj9":  [60, 64, 67, 71, 74],
}

_SCALES: dict[str, list[int]] = {
    "major":          [0, 2, 4, 5, 7, 9, 11],
    "minor":          [0, 2, 3, 5, 7, 8, 10],
    "natural minor":  [0, 2, 3, 5, 7, 8, 10],
    "pentatonic":     [0, 2, 4, 7, 9],
    "minor pentatonic": [0, 3, 5, 7, 10],
    "blues":          [0, 3, 5, 6, 7, 10],
    "dorian":         [0, 2, 3, 5, 7, 9, 10],
    "mixolydian":     [0, 2, 4, 5, 7, 9, 10],
}

_NOTE_NAMES = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}

_DEFAULT_PROGRESSIONS: dict[str, list[str]] = {
    "rock":    ["Am", "F",  "C",  "G"],
    "pop":     ["C",  "G",  "Am", "F"],
    "jazz":    ["Dm7", "G7", "Cmaj7", "Am7"],
    "hip-hop": ["Am", "G",  "Am", "G"],
    "hiphop":  ["Am", "G",  "Am", "G"],
    "trap":    ["Am", "G",  "Am", "G"],
    "dnb":     ["Am", "G"],
    "funk":    ["Am7", "Dm7", "Am7", "Dm7"],
    "blues":   ["A",  "A",  "D",  "A"],
    "default": ["C",  "Am", "F",  "G"],
}


def _root_midi(key: str, octave: int = 3) -> int:
    note = key.rstrip("0123456789").replace(" ", "")
    return 12 * (octave + 1) + _NOTE_NAMES.get(note, 0)


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
            n(o+0.0, KICK, 0.65)
            n(o+1.0, HH_C, 0.80); n(o+3.0, HH_C, 0.80)
            for i in range(4):
                n(o+i,      RIDE, 0.75)
                n(o+i+0.67, RIDE, 0.52)

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


@tool
def write_pattern(
    track_index: int,
    instrument: str,
    genre: str = "rock",
    bpm: int = 120,
    bars: int = 2,
    key: str = "C",
    scale: str = "minor",
    chord_progression: list = None,
    style: str = "basic",
    slot: int = 0,
) -> str:
    """Generiert und schreibt ein musikalisches Pattern für ein Instrument direkt in Bitwig.

    Instrument-Typen (instrument-Parameter):
      Drums:    "MT-PowerDrumKit"
      808:      "808 Kick", "808 Snare"
      Bass:     "FM-4", "Surge XT", "bass"
      Chords:   "Phase-4", "Polysynth", "VPO Strings", "VPO Brass", "VPO Choir", "UprightPianoKW"
      Melodie:  "lead", "melody"

    genre: rock | hip-hop | trap | jazz | dnb | funk | pop
    style: basic | full | arpeggio | staccato | sustained
    key:   C D E F G A B  (mit # oder b)
    scale: major | minor | pentatonic | blues | dorian
    chord_progression: ["Am","F","C","G"] — für Chord/Pad-Instrumente (optional)
    bars:  Anzahl Takte (1–4 empfohlen)
    slot:  Clip-Slot (0=erster Clip)
    """
    from src.bitwig_executor import compose_notes

    inst_lower = instrument.lower().replace("-", "").replace(" ", "")
    chords = chord_progression or []

    drum_keywords  = ["drum", "percussion", "mtpowerdrumkit"]
    bass_keywords  = ["fm4", "surgext", "surge", "bass"]
    chord_keywords = ["phase4", "polysynth", "poly", "strings", "choir",
                      "brass", "piano", "uprightpiano", "pad", "chord"]

    if "808kick" in inst_lower:
        notes = _808_kick(genre, bars); ptype = "808-kick"
    elif "808snare" in inst_lower:
        notes = _808_snare(genre, bars); ptype = "808-snare"
    elif any(k in inst_lower for k in drum_keywords):
        notes = _drums(genre, bars, style); ptype = "drums"
    elif any(k in inst_lower for k in bass_keywords):
        notes = _bass(genre, bars, _root_midi(key, octave=2), style); ptype = "bass"
    elif any(k in inst_lower for k in chord_keywords):
        if not chords:
            chords = _DEFAULT_PROGRESSIONS.get(genre, _DEFAULT_PROGRESSIONS["default"])
        notes = _chords(genre, bars, chords, style); ptype = "chords"
    else:
        notes = _melody(genre, bars, _root_midi(key, octave=3), scale, style); ptype = "melody"

    result = compose_notes({
        "context_type": "track",
        "target": {"bpm": bpm, "genre": genre},
        "track": {"index": track_index, "name": instrument, "instrument": instrument},
        "summary": f"{genre} {ptype} für {instrument} ({bars} Takte)",
        "steps": [{
            "type": "write_notes",
            "args": {"track_index": track_index, "slot": slot,
                     "length_beats": bars * 4, "notes": notes},
            "status": "pending", "note": "",
        }],
    })
    return f"[write_pattern] {ptype} | {len(notes)} Noten | {result}"
