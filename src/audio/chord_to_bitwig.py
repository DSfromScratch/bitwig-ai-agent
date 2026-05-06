"""
Chordonomicon → Bitwig MIDI-Noten Konverter.

Parst Akkord-Progressionen aus der KB und erzeugt
bitwig_note_pattern-kompatible JSON-Arrays für Bass und Chords.
"""

from __future__ import annotations
import re

# ── Akkord-Wurzeln (MIDI, Oktave 3) ─────────────────────────────────────────

ROOT = {
    "C": 48, "Cs": 49, "Db": 49,
    "D": 50, "Ds": 51, "Eb": 51,
    "E": 52,
    "F": 53, "Fs": 54, "Gb": 54,
    "G": 55, "Gs": 56, "Ab": 56,
    "A": 57, "As": 58, "Bb": 58,
    "B": 59,
}

# ── Intervalle pro Akkord-Typ ─────────────────────────────────────────────────

INTERVALS = {
    "maj":   [0, 4, 7],
    "min":   [0, 3, 7],
    "dim":   [0, 3, 6],
    "aug":   [0, 4, 8],
    "sus2":  [0, 2, 7],
    "sus4":  [0, 5, 7],
    "maj7":  [0, 4, 7, 11],
    "7":     [0, 4, 7, 10],
    "m7":    [0, 3, 7, 10],
    "dim7":  [0, 3, 6, 9],
    "add9":  [0, 4, 7, 14],
}


def parse_chord(token: str) -> tuple[int, list[int]] | None:
    """
    Parst einen Akkord-Token aus dem Chordonomicon-Format.

    Beispiele: Am, Amin, F, Gs, Fsmin, Csdim, Gssus2, Bb, G7, Cmaj7

    Returns:
        (root_midi, interval_list) oder None bei Fehler
    """
    t = token.strip()
    if not t:
        return None

    # Wurzel-Note extrahieren: 1-2 Buchstaben + optionales 's'/'b' für #/b
    root_match = re.match(r'^([A-G][sb]?)', t)
    if not root_match:
        return None

    root_str = root_match.group(1)
    rest = t[len(root_str):]

    root_midi = ROOT.get(root_str)
    if root_midi is None:
        return None

    # Akkord-Typ bestimmen
    chord_type = "maj"  # default: Dur
    rest_lower = rest.lower()

    if rest_lower in ("min", "m", "minor"):
        chord_type = "min"
    elif rest_lower == "dim7":
        chord_type = "dim7"
    elif rest_lower in ("dim", "o"):
        chord_type = "dim"
    elif rest_lower == "aug":
        chord_type = "aug"
    elif rest_lower == "sus2":
        chord_type = "sus2"
    elif rest_lower == "sus4":
        chord_type = "sus4"
    elif rest_lower == "maj7":
        chord_type = "maj7"
    elif rest_lower == "m7":
        chord_type = "m7"
    elif rest_lower == "7":
        chord_type = "7"
    elif rest_lower == "add9":
        chord_type = "add9"
    elif rest_lower.startswith("min") or rest_lower.startswith("m"):
        chord_type = "min"

    return root_midi, INTERVALS[chord_type]


def chord_to_notes(token: str, octave_shift: int = 0) -> list[int]:
    """Gibt absolute MIDI-Noten für einen Akkord zurück."""
    result = parse_chord(token)
    if result is None:
        return []
    root, intervals = result
    return [root + i + octave_shift * 12 for i in intervals]


def parse_chordonomicon(text: str) -> dict:
    """
    Parst einen Chordonomicon-Eintrag.

    Format:
        Genre: pop | Chords: <verse_1> Am F G Am <chorus_1> F G Am | Decade: 2020.0

    Returns:
        {
            "genre": "pop",
            "decade": 2020.0,
            "sections": {
                "verse_1": ["Am", "F", "G", "Am"],
                "chorus_1": ["F", "G", "Am"],
            }
        }
    """
    genre_m   = re.search(r'Genre:\s*([^|]+)', text)
    decade_m  = re.search(r'Decade:\s*([\d.]+)', text)
    chords_m  = re.search(r'Chords:\s*(.+?)(?:\s*\|?\s*Decade|$)', text)

    genre  = genre_m.group(1).strip()  if genre_m  else "unknown"
    decade = float(decade_m.group(1)) if decade_m else 0.0

    sections: dict[str, list[str]] = {}
    if chords_m:
        raw = chords_m.group(1).strip()
        # Sektions-Tags: <verse_1>, <chorus_1>, etc.
        parts = re.split(r'<(\w+)>', raw)
        # parts[0] = Text vor erstem Tag (oft leer)
        # parts[1] = Tag-Name, parts[2] = Akkorde, ...
        current = "intro"
        if parts[0].strip():
            tokens = [t for t in parts[0].split() if t]
            if tokens:
                sections[current] = tokens
        for i in range(1, len(parts), 2):
            tag    = parts[i]
            chords = parts[i + 1].split() if i + 1 < len(parts) else []
            sections[tag] = [c for c in chords if c]

    return {"genre": genre, "decade": decade, "sections": sections}


def humanize_velocity(
    notes: list[dict],
    variance: float = 0.06,
    curve: list[float] | None = None,
    seed: int = 0,
) -> list[dict]:
    """Fügt menschliche Velocity-Variation hinzu.

    Args:
        notes:    Liste von Note-Dicts mit step/pitch/vel/dur
        variance: Gaußsches Rauschen σ (0.06 ≈ ±6%)
        curve:    Optionale Hüllkurve [0.0–1.0], len ≥ 2.
                  Crescendo: [0.7, 1.0], Decrescendo: [1.0, 0.6]
        seed:     Zufalls-Seed für Reproduzierbarkeit

    Returns:
        Neue Liste mit angepassten Velocities (Originale unverändert)
    """
    import random
    rng = random.Random(seed)
    if not notes:
        return notes
    max_step = max(n["step"] for n in notes) or 1.0
    result = []
    for n in notes:
        vel = n["vel"]
        if curve and len(curve) >= 2:
            pos = n["step"] / max_step
            idx_f = pos * (len(curve) - 1)
            idx_lo = int(idx_f)
            idx_hi = min(idx_lo + 1, len(curve) - 1)
            frac = idx_f - idx_lo
            curve_val = curve[idx_lo] * (1 - frac) + curve[idx_hi] * frac
            vel *= curve_val
        # Ghost Notes bekommen weniger Varianz
        effective_variance = variance * 0.5 if vel < 0.5 else variance
        vel += rng.gauss(0, effective_variance)
        vel = max(0.05, min(1.0, vel))
        result.append({**n, "vel": round(vel, 3)})
    return result


def voice_lead_chord(
    prev_notes: list[int],
    new_chord_notes: list[int],
) -> list[int]:
    """Findet die Inversion des neuen Akkords mit minimaler Stimmführung.

    Probiert alle Oktav-Varianten aller Töne des neuen Akkords und wählt
    die Voicing-Kombination mit der geringsten Gesamtbewegung gegenüber
    dem vorherigen Akkord.

    Args:
        prev_notes:      MIDI-Pitches des vorherigen Akkords
        new_chord_notes: MIDI-Pitches des neuen Akkords (Root-Position)

    Returns:
        MIDI-Pitches des neuen Akkords in optimaler Inversion
    """
    if not prev_notes or not new_chord_notes:
        return new_chord_notes

    from itertools import product

    best_voicing = new_chord_notes[:]
    best_cost = float("inf")

    for shifts in product([-12, 0, 12], repeat=len(new_chord_notes)):
        voicing = sorted([new_chord_notes[i] + shifts[i] for i in range(len(new_chord_notes))])
        # Sinnvollen Pitch-Bereich einhalten (MIDI 36–84 für Chords)
        if not all(36 <= p <= 84 for p in voicing):
            continue
        # Stimmführungskosten: jede neue Note → nächste Vorgänger-Note
        cost = sum(min(abs(p - q) for q in prev_notes) for p in voicing)
        if cost < best_cost:
            best_cost = cost
            best_voicing = voicing

    return best_voicing


def progression_to_pattern(
    chords: list[str],
    beats_per_chord: float = 2.0,
    bass_octave: int = 0,      # 0 = Oktave 3 (C3=48)
    chord_octave: int = 1,     # +1 Oktave höher als Bass
    bass_vel: float = 0.85,
    chord_vel: float = 0.65,
    bass_fill: bool = True,
) -> dict:
    """
    Konvertiert eine Liste von Akkord-Tokens in Bass- und Chord-Pattern.

    Returns:
        {
            "length_beats": float,
            "bass": [...],    # note_pattern JSON für Bass-Track
            "chords": [...],  # note_pattern JSON für Chord-Track
        }
    """
    bass_notes        = []
    chord_notes       = []
    length_beats      = len(chords) * beats_per_chord
    prev_chord_pitches: list[int] = []

    for i, token in enumerate(chords):
        beat = i * beats_per_chord
        result = parse_chord(token)
        if result is None:
            prev_chord_pitches = []
            continue
        root, intervals = result

        # ── Bass: Walking-Linie mit rhythmischer Bewegung ────────────────────
        bass_root = root + bass_octave * 12
        # 1) Grundton auf dem Downbeat (mit Kick zusammen, aber kurz)
        bass_notes.append({
            "step": beat,
            "pitch": bass_root,
            "vel": bass_vel,
            "dur": 0.75,  # kurz — Platz für Bewegung lassen
        })
        if beats_per_chord >= 2:
            # 2) Oktavsprung auf Beat 1 — Energie, gegen die Snare
            bass_notes.append({
                "step": beat + 1.0,
                "pitch": bass_root + 12,  # Oktave hoch
                "vel": bass_vel * 0.80,
                "dur": 0.5,
            })
            # 3) Durchgangsnote auf Beat 1.75 — Antizipation des nächsten Akkords
            if bass_fill:
                next_token = chords[(i + 1) % len(chords)]
                next_result = parse_chord(next_token)
                if next_result:
                    next_root = next_result[0] + bass_octave * 12
                    approach = bass_root + 1 if next_root > bass_root else bass_root - 1
                    bass_notes.append({
                        "step": beat + beats_per_chord - 0.25,
                        "pitch": approach,
                        "vel": bass_vel * 0.70,
                        "dur": 0.25,
                    })

        # ── Chords: Voice Leading + rhythmisches Comping ─────────────────────
        chord_dur_main = 1.4
        chord_dur_ant  = 0.45

        raw_chord_pitches = [root + interval + chord_octave * 12 for interval in intervals]
        voiced_chord_pitches = voice_lead_chord(prev_chord_pitches, raw_chord_pitches)
        prev_chord_pitches = voiced_chord_pitches

        for pitch in voiced_chord_pitches:
            chord_notes.append({
                "step": beat,
                "pitch": pitch,
                "vel": chord_vel,
                "dur": chord_dur_main,
            })
            if beats_per_chord >= 2:
                chord_notes.append({
                    "step": beat + 1.5,
                    "pitch": pitch,
                    "vel": chord_vel * 0.85,
                    "dur": chord_dur_ant,
                })

    return {
        "length_beats": length_beats,
        "bass":   bass_notes,
        "chords": chord_notes,
    }


def query_chordonomicon(genre: str, n: int = 5) -> list[dict]:
    """Holt n Akkordprogressionen für ein beliebiges Genre aus Neo4j.

    Args:
        genre: Genre-Name (z.B. "pop", "rock", "jazz", "pop rock")
        n:     Anzahl Ergebnisse
    """
    import os
    from neo4j import GraphDatabase

    uri  = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER",     "neo4j")
    pwd  = os.getenv("NEO4J_PASSWORD", "neo4jllm")

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        driver.verify_connectivity()
    except Exception as e:
        raise ConnectionError(
            f"Neo4j nicht erreichbar ({uri}). "
            "Bitte starten: `make neo4j-start` oder `docker start neo4j`."
        ) from e

    results = []
    with driver.session() as s:
        rows = s.run(
            """
            MATCH (k:KnowledgeQA)
            WHERE k.source = 'Chordonomicon'
              AND toLower(k.text) CONTAINS $genre
            RETURN k.text AS text
            LIMIT $n
            """,
            genre=genre.lower().strip(),
            n=n,
        ).data()
        for row in rows:
            parsed = parse_chordonomicon(row["text"])
            results.append(parsed)
    driver.close()
    return results


# ── Melodie-Generator ─────────────────────────────────────────────────────────

NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

# Pentatonische Skalen (Intervalle ab Root)
PENTATONIC = {
    "minor": [0, 3, 5, 7, 10],   # 1 b3 4 5 b7
    "major": [0, 2, 4, 7, 9],    # 1 2 3 5 6
}

# Diatonische Skalen (7-töning)
DIATONIC = {
    "major": [0, 2, 4, 5, 7, 9, 11],  # Ionian
    "minor": [0, 2, 3, 5, 7, 8, 10],  # Aeolian
}

# Blues-Skala (Pentatonik + Blue Note)
BLUES_SCALE = {
    "minor": [0, 3, 5, 6, 7, 10],  # b3 4 b5 5 b7
    "major": [0, 2, 3, 4, 7, 9],   # 2 b3 3 5 6
}

# Rhythmus-Muster für 2 Beats (wiederholt über Clip-Länge)
RHYTHM_PATTERNS = [
    [1.0, 1.0],               # zwei Viertel
    [0.5, 0.5, 1.0],          # zwei Achtel + Viertel
    [1.0, 0.5, 0.5],          # Viertel + zwei Achtel
    [0.5, 0.5, 0.5, 0.5],     # vier Achtel
    [1.5, 0.5],               # punktierte Viertel + Achtel
    [0.5, 1.5],               # Achtel + punktierte Viertel
]

# Genre-spezifische Rhythmusmuster
RHYTHM_PATTERNS_BY_GENRE: dict[str, list[list[float]]] = {
    "jazz":      [[0.67, 0.33, 1.0], [1.0, 0.33, 0.67], [0.67, 0.67, 0.67],
                  [1.5, 0.5], [0.33, 0.33, 0.33, 1.0]],   # Swing-Triolen
    "blues":     [[1.5, 0.5], [0.5, 0.5, 1.0], [1.0, 0.5, 0.5],
                  [0.67, 0.33, 1.0]],                      # Shuffle-feel
    "metal":     [[0.25, 0.25, 0.5], [0.25, 0.25, 0.25, 0.25],
                  [0.5, 0.25, 0.25], [0.25, 0.5, 0.25]],  # 16tel-Läufe
    "trap":      [[0.25, 0.25, 0.5], [0.5, 0.25, 0.25, 0.5],
                  [0.25, 0.75], [0.5, 0.5, 0.5, 0.5]],    # Hi-Hat-Patterns
    "default":   RHYTHM_PATTERNS,
}
RHYTHM_PATTERNS_BY_GENRE["rock"] = RHYTHM_PATTERNS_BY_GENRE["default"]
RHYTHM_PATTERNS_BY_GENRE["pop"]  = RHYTHM_PATTERNS_BY_GENRE["default"]

# Melodie-Profile: steuern Kontur, Skala und Sprungweite pro Genre
GENRE_MELODY_PROFILES: dict[str, dict] = {
    "pop":     {"scale_type": "pentatonic", "peak_pos": 0.60, "max_steps": 1, "end_on_tonic": True},
    "rock":    {"scale_type": "pentatonic", "peak_pos": 0.55, "max_steps": 2, "end_on_tonic": True},
    "jazz":    {"scale_type": "diatonic",   "peak_pos": 0.75, "max_steps": 2, "end_on_tonic": False},
    "blues":   {"scale_type": "blues",      "peak_pos": 0.50, "max_steps": 2, "end_on_tonic": False},
    "metal":   {"scale_type": "pentatonic", "peak_pos": 0.40, "max_steps": 2, "end_on_tonic": True},
    "trap":    {"scale_type": "pentatonic", "peak_pos": 0.50, "max_steps": 1, "end_on_tonic": False},
    "default": {"scale_type": "pentatonic", "peak_pos": 0.60, "max_steps": 1, "end_on_tonic": True},
}
GENRE_MELODY_PROFILES["bossa nova"] = GENRE_MELODY_PROFILES["jazz"]
GENRE_MELODY_PROFILES["hard rock"]  = GENRE_MELODY_PROFILES["rock"]
GENRE_MELODY_PROFILES["heavy metal"] = GENRE_MELODY_PROFILES["metal"]


def detect_key(chords: list[str]) -> tuple[int, str]:
    """
    Erkennt Tonart aus Akkordfolge.
    Gibt (root_midi, mode) zurück — mode ist 'minor' oder 'major'.
    """
    minor_count = 0
    major_count = 0
    root_candidate = None

    for token in chords:
        result = parse_chord(token)
        if result is None:
            continue
        root, intervals = result
        if intervals == INTERVALS["min"] or intervals == INTERVALS.get("m7", [0,3,7,10]):
            minor_count += 1
            if root_candidate is None:
                root_candidate = root
        elif intervals == INTERVALS["maj"]:
            major_count += 1
            if root_candidate is None:
                root_candidate = root

    if root_candidate is None:
        root_candidate = ROOT["C"]  # Fallback C

    mode = "minor" if minor_count >= major_count else "major"
    return root_candidate, mode


def generate_melody(
    chords: list[str],
    length_beats: float = 8.0,
    melody_octave: int = 2,     # +2 Oktaven über Root = klar über Chords (Bitwig C4–C5)
    vel_base: float = 0.78,
    seed: int = 42,
    genre: str = "default",
    scale_type: str | None = None,    # None = auto aus Genre-Profil
    end_on_tonic: bool | None = None, # None = auto aus Genre-Profil
) -> list[dict]:
    """
    Generiert eine melodische Lead-Linie aus einer Akkordprogression.

    Algorithmus:
      1. Tonart erkennen (Dur/Moll)
      2. Skala aufbauen (Pentatonik/Diatonisch/Blues je nach Genre-Profil)
      3. Genre-abhängige Kontur: Peak-Position und Sprung-Geschwindigkeit
      4. Rhythmus-Muster genre-spezifisch variieren
      5. Harmonie-Noten bevorzugen (Akkordtöne auf betonten Beats)

    Args:
        chords:        Akkordliste (z.B. ["Amin", "F", "G", "Amin"])
        length_beats:  Clip-Länge in Beats
        melody_octave: Oktav-Offset über Root (2 = zwei Oktaven höher)
        vel_base:      Basis-Velocity (0.0–1.0)
        seed:          Zufalls-Seed für Reproduzierbarkeit
        genre:         Genre für Profil-Lookup (z.B. "jazz", "metal")
        scale_type:    Override Skalentyp: "pentatonic"/"diatonic"/"blues"
        end_on_tonic:  Override ob letzte Note Tonika sein soll

    Returns:
        Liste von Noten-Dicts {step, pitch, vel, dur}
    """
    import random
    rng = random.Random(seed)

    # Genre-Profil auflösen
    _profile   = GENRE_MELODY_PROFILES.get(genre, GENRE_MELODY_PROFILES["default"])
    _scale_type  = scale_type   if scale_type   is not None else _profile["scale_type"]
    _end_tonic   = end_on_tonic if end_on_tonic is not None else _profile["end_on_tonic"]
    _peak_pos    = _profile["peak_pos"]    # 0.0–1.0: wo im Clip der Peak liegt
    _max_steps   = _profile["max_steps"]  # Skala-Schritte pro Beat (1=smooth, 2=aggressiv)

    root, mode = detect_key(chords)

    # Skalentyp wählen
    if _scale_type == "diatonic":
        scale_intervals = DIATONIC[mode]
    elif _scale_type == "blues":
        scale_intervals = BLUES_SCALE[mode]
    else:
        scale_intervals = PENTATONIC[mode]

    # Genre-spezifische Rhythmusmuster
    rhythm_pool = RHYTHM_PATTERNS_BY_GENRE.get(genre, RHYTHM_PATTERNS)

    # Skala aufbauen (2 Oktaven ab Melodie-Root)
    melody_root = root + melody_octave * 12
    scale = []
    for octave in range(3):
        for interval in scale_intervals:
            pitch = melody_root + octave * 12 + interval
            if 72 <= pitch <= 88:
                scale.append(pitch)
    scale = sorted(set(scale))

    if not scale:
        return []

    n_scale = len(scale)

    # Akkordtöne für harmonische Führung
    beats_per_chord = length_beats / max(len(chords), 1)
    chord_tones_at_beat: dict[float, set] = {}
    for i, token in enumerate(chords):
        result = parse_chord(token)
        if result:
            r, ivs = result
            tones = {(r + iv + melody_octave * 12) % 128 for iv in ivs}
            chord_tones_at_beat[i * beats_per_chord] = tones

    # Dynamische Kontur basierend auf _peak_pos
    # peak_step: bei welchem Kontur-Index der Peak liegt (1–4 in 6-Punkt-Kontur)
    peak_step = max(1, min(4, round(_peak_pos * 5)))
    quint_idx = next((i for i, p in enumerate(scale) if p % 12 == (root + 7) % 12), n_scale // 2)

    contour_indices = []
    # Aufstieg: quint_idx → peak (n_scale-1)
    for k in range(peak_step + 1):
        t = k / peak_step if peak_step > 0 else 1.0
        idx = int(quint_idx + t * (n_scale - 1 - quint_idx))
        contour_indices.append(min(idx, n_scale - 1))
    # Abstieg + Auflösung: peak → tonika (0)
    post_steps = max(2, 5 - peak_step)
    for k in range(1, post_steps + 1):
        t = k / post_steps
        idx = int((n_scale - 1) * (1.0 - t))
        contour_indices.append(max(0, idx))

    # Rhythmus-Pattern für die gesamte Länge
    pattern_idx = rng.randint(0, len(rhythm_pool) - 1)
    rhythm = rhythm_pool[pattern_idx]

    notes = []
    beat = 0.0
    scale_idx = contour_indices[0]

    while beat < length_beats - 0.1:
        contour_progress = beat / max(length_beats, 1)
        target_contour_idx = min(
            int(contour_progress * len(contour_indices)),
            len(contour_indices) - 1,
        )
        target_idx = contour_indices[target_contour_idx]

        # Genre-abhängige Schrittweite
        if scale_idx < target_idx:
            scale_idx = min(scale_idx + rng.randint(1, _max_steps), target_idx)
        elif scale_idx > target_idx:
            scale_idx = max(scale_idx - rng.randint(1, _max_steps), target_idx)

        # Akkordton auf betonten Beats bevorzugen
        is_strong_beat = (beat % 2.0) < 0.1
        if is_strong_beat:
            nearest_chord_start = int(beat / beats_per_chord) * beats_per_chord
            chord_tones = chord_tones_at_beat.get(nearest_chord_start, set())
            if chord_tones:
                for offset in range(4):
                    for direction in [0, 1, -1, 2, -2]:
                        candidate_idx = max(0, min(n_scale - 1, scale_idx + direction + offset))
                        if scale[candidate_idx] % 12 in {ct % 12 for ct in chord_tones}:
                            scale_idx = candidate_idx
                            break
                    else:
                        continue
                    break

        pitch = scale[max(0, min(n_scale - 1, scale_idx))]

        dur = rhythm[len(notes) % len(rhythm)]
        dur = min(dur, length_beats - beat)
        if dur < 0.1:
            break

        vel_factor = 1.0 if is_strong_beat else rng.uniform(0.82, 0.95)
        vel = min(1.0, vel_base * vel_factor)

        notes.append({
            "step": round(beat, 4),
            "pitch": pitch,
            "vel": round(vel, 3),
            "dur": round(dur, 4),
        })

        beat += dur

    # Letzte Note: optional auf Tonika auflösen
    if _end_tonic and notes:
        tonic_notes = [s for s in scale if s % 12 == melody_root % 12]
        if tonic_notes:
            notes[-1]["pitch"] = min(tonic_notes, key=lambda x: abs(x - notes[-1]["pitch"]))

    return notes
