"""
Pattern-Tool für den Agent: write_pattern @tool.
Daten: music_data.py | Generatoren: pattern_generators.py
"""
from __future__ import annotations
from langchain_core.tools import tool

from src.agent.tools.music_data import (  # noqa: F401
    _CHORDS, _SCALES, _NOTE_NAMES, _DEFAULT_PROGRESSIONS, _root_midi,
)
from src.agent.tools.pattern_generators import (  # noqa: F401
    _drums, _bass, _chords, _melody, _808_kick, _808_snare,
)

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

    drum_keywords  = ["drum", "percussion", "mtpowerdrumkit", "vd-", "vdheavy"]
    bass_keywords  = ["fm4", "surgext", "surge", "bass", "vb-", "vbroyal", "vbmellow"]
    chord_keywords = ["phase4", "polysynth", "poly", "strings", "choir",
                      "brass", "piano", "uprightpiano", "pad", "chord",
                      "vg-", "vgironk2", "vgsilk2", "vgiron", "vgsilk"]

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
