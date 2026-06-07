"""Parser für seed-Song `note_plan`-Strings → write_pattern_raw-Ground-Truth.

Format (Beispiel aus Queen - Under Pressure):
    Notenplan Under Pressure (D major, 117 BPM):
      Bass-Track (FM-4): Ikonische Bassline:
        D3=62 [s0,dur1], D3=62 [s2,dur1], Bb2=58 [s5,dur1]
      Drums: Kick=36 [s0,s4,s8,s12], Snare=38 [s4,s12]

Wir extrahieren pro Track-Zeile eine Liste von Noten im write_pattern_raw-Schema:
    [{"pitch": 62, "start": 0, "dur": 1, "vel": 0.8}, ...]

Wird verwendet von:
  - scripts/_neo4j_song_prompts.py (Ground-Truth-Strategy-A für DPO)
"""
from __future__ import annotations

import re
from typing import Any


# `D3=62 [s0,dur1]` ODER `Kick=36 [s0,s4,s8,s12]`
_NOTE_RE = re.compile(
    r"""
    (?P<name>[A-Ga-g][b#]?\d?|[A-Za-z]+)   # NoteName+Oct (D3) ODER Drum-Word (Kick)
    \s*=\s*
    (?P<midi>\d{1,3})                       # MIDI-Pitch
    \s*\[
    (?P<spec>[^\]]+)                        # Step/Dur-Spezifikation
    \]
    """,
    re.VERBOSE,
)

_TRACK_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9\-_/ ]*?)(?:\s*\([^)]*\))?\s*:\s*(.*)$")
_HEADER_RE     = re.compile(
    r"Notenplan\s+.*?\((?P<key>[A-G][b#]?\s+(?:major|minor))[^)]*",
    re.IGNORECASE,
)
_HEADER_BPM_RE = re.compile(r"(\d+)\s*BPM", re.IGNORECASE)


def _parse_spec(spec: str, default_dur: float = 0.5) -> list[tuple[float, float]]:
    """`s0,s4,s8,s12` → [(0,default_dur), (4,default_dur), ...]
       `s0,dur1`      → [(0, 1.0)]
       `s5,dur1`      → [(5, 1.0)]
       `s0,dur8,Slide`→ [(0, 8.0)]  (Modifier ignoriert)
    """
    starts: list[float] = []
    dur: float | None = None
    for tok in re.split(r"[,\s]+", spec.strip()):
        if not tok:
            continue
        m = re.match(r"s(-?\d+(?:\.\d+)?)$", tok, re.IGNORECASE)
        if m:
            starts.append(float(m.group(1)))
            continue
        m = re.match(r"dur(\d+(?:\.\d+)?)$", tok, re.IGNORECASE)
        if m:
            dur = float(m.group(1))
            continue
        # Modifier wie "Slide", "rampup", etc. — ignorieren
    d = dur if dur is not None else default_dur
    return [(s, d) for s in starts]


def parse_note_plan(plan: str, step_unit_beats: float = 0.5) -> dict[str, Any]:
    """Parst einen note_plan-String in strukturierte Daten.

    step_unit_beats: Wie viele Beats ein 's'-Step entspricht. Default 0.5
                     (16th-grid: 16 steps = 8 beats = 2 Takte 4/4).

    Returns:
        {
          "key": "D major" | None,
          "bpm": 117 | None,
          "tracks": [
              {"role": "Bass-Track", "instrument": "FM-4",
               "notes": [{"pitch":62,"start":0,"dur":0.5,"vel":0.8}, ...]},
              ...
          ]
        }
    """
    out: dict[str, Any] = {"key": None, "bpm": None, "tracks": []}
    if not plan:
        return out

    # Header
    m = _HEADER_RE.search(plan)
    if m:
        out["key"] = m.group("key")
    bpm_m = _HEADER_BPM_RE.search(plan.split("\n", 1)[0]) if plan else None
    if bpm_m:
        try:
            out["bpm"] = int(bpm_m.group(1))
        except ValueError:
            pass

    current_role: str | None = None
    current_instrument: str | None = None
    current_notes: list[dict] = []

    def _flush():
        if current_role and current_notes:
            out["tracks"].append({
                "role":       current_role,
                "instrument": current_instrument,
                "notes":      list(current_notes),
            })

    for raw_line in plan.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("→"):
            continue
        if line.strip().startswith("Notenplan"):
            continue

        # Neue Track-Zeile?
        m = _TRACK_LINE_RE.match(line)
        is_new_track = m and ("=" in (m.group(2) or "") or not current_role)
        # Heuristik: nur als neuer Track erkennen, wenn rolle nicht mit einem note-pattern beginnt
        if m and "=" not in line.split(":", 1)[0]:
            # flush den alten Track
            _flush()
            current_notes = []
            current_role = m.group(1).strip()
            # Instrument aus "( ... )" extrahieren
            inst_m = re.search(r"\(([^)]+)\)", raw_line)
            current_instrument = inst_m.group(1).strip() if inst_m else None
            content = m.group(2) or ""
        else:
            content = line

        # Notes aus content extrahieren
        for nm in _NOTE_RE.finditer(content):
            try:
                pitch = int(nm.group("midi"))
            except ValueError:
                continue
            if not (0 <= pitch <= 127):
                continue
            for start_step, dur_step in _parse_spec(nm.group("spec")):
                current_notes.append({
                    "pitch": pitch,
                    "start": round(start_step * step_unit_beats, 4),
                    "dur":   round(max(dur_step * step_unit_beats, 0.0625), 4),
                    "vel":   0.8,
                })
    _flush()
    return out


def to_write_pattern_raw_call(track: dict, track_index: int = 0,
                              bpm: int = 120,
                              key: str | None = None) -> dict:
    """Konvertiert einen geparsten Track zu einem write_pattern_raw-Tool-Call.
    Returns dict im {"tool":"write_pattern_raw","args":{...}}-Format."""
    notes = track.get("notes", [])
    if not notes:
        return {}
    max_end = max((n["start"] + n["dur"]) for n in notes)
    # Auf nächsten ganzen Takt aufrunden (4/4)
    length = max(4.0, ((int(max_end) // 4) + 1) * 4.0)
    args = {
        "track_index":  track_index,
        "notes":        notes,
        "length_beats": length,
        "instrument":   track.get("instrument") or track.get("role") or "raw",
        "bpm":          bpm,
    }
    if key:
        args["key"] = key
    return {"tool": "write_pattern_raw", "args": args}
