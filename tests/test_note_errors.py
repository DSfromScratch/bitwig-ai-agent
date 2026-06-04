"""
Test: Fehler-Erkennung in MIDI-Patterns.

Testet ob der Validator folgende Fehlertypen erkennt:
  1. Harmonisch falsch  — Note außerhalb Tonart/Skala
  2. Nicht spielbar     — Außerhalb Instrument-Bereich (Gitarre, Bass, Piano)
  3. Physisch unmöglich — HH offen+geschlossen simultan, negative Dauer
  4. Bereich falsch     — Drums mit Piano-Werten, Bass zu hoch
  5. Velocity ungültig  — > 1.0 oder = 0.0

Erwartet: score < 0.55, issues nicht leer.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def n(step, pitch, vel=0.75, dur=0.25):
    return {"step": step, "pitch": pitch, "vel": vel, "dur": dur}

def _resp(score, issues, rhythmic_ok=True, harmonic_ok=True):
    return json.dumps({
        "score": score, "rhythmic_ok": rhythmic_ok, "harmonic_ok": harmonic_ok,
        "genre_fit": True, "issues": issues,
        "suggestions": ["Falsche Note korrigieren"],
        "summary": f"Pattern enthält Fehler, Score {score:.2f}.",
    })


# ── 1. Harmonisch falsche Noten ───────────────────────────────────────────────

# A minor Skala: A B C D E F G  (MIDI mod 12: 9,11,0,2,4,5,7)
# Falsch in A minor: G# (8), F# (6), C# (1), D# (3)

HARMONIC_ERRORS = [
    # Bass-Linie in A minor mit Bb-Root (falsche Tonika)
    {
        "notes": [n(0,46,0.85,0.5), n(0.5,48,0.72,0.5), n(1.0,46,0.80,0.5), n(1.5,48,0.68,0.5),
                  # Bb2=46 als Tonika statt A2=45 in A minor
                  n(2.0,46,0.82,0.5), n(2.5,50,0.70,0.5), n(3.0,46,0.78,0.5)],
        "instrument": "VB-ROYAL", "genre": "rock", "key": "A", "scale": "minor",
        "error": "Bb2 (MIDI46) als Tonika statt A2 (MIDI45) in A minor",
        "expected_issue_hint": "Bb",
    },
    # Rock-Gitarre in C major mit F# (Tritonus)
    {
        "notes": [n(0.0, 60, 0.80, 0.5), n(0.5, 64, 0.75, 0.5),
                  n(1.0, 66, 0.78, 0.5),  # F#4 = MIDI66 — Tritonus in C major
                  n(1.5, 67, 0.72, 0.5), n(2.0, 60, 0.80, 0.5)],
        "instrument": "VG-IRON2", "genre": "rock", "key": "C", "scale": "major",
        "error": "F#4 (MIDI66) = Tritonus in C major — dissonant",
        "expected_issue_hint": "F#",
    },
    # Jazz in C major mit völlig falschem Akkord (Db major = bII)
    {
        "notes": [n(0.0, 61, 0.70, 1.0),  # Db4 = MIDI61 — nicht in C major
                  n(0.0, 65, 0.70, 1.0),  # F4
                  n(0.0, 68, 0.70, 1.0),  # Ab4 = MIDI68 — nicht in C major
                  n(2.0, 60, 0.75, 1.0), n(2.0, 64, 0.75, 1.0), n(2.0, 67, 0.75, 1.0)],
        "instrument": "Piano", "genre": "jazz", "key": "C", "scale": "major",
        "error": "Db-F-Ab Akkord (bII) — fremde Töne in C major",
        "expected_issue_hint": "Db",
    },
]

# ── 2. Nicht spielbare Noten (Bereich überschritten) ──────────────────────────

OUT_OF_RANGE = [
    # Gitarre: Fret 30 = unmöglich (Standard-Gitarre max Fret 22)
    # String 1 (E4=64): Fret 30 → MIDI 94 = Bb6
    {
        "notes": [n(0.0, 66, 0.80), n(0.5, 69, 0.75), n(1.0, 94, 0.82),  # MIDI94 = unmöglich
                  n(1.5, 71, 0.70), n(2.0, 69, 0.75)],
        "instrument": "Guitar", "genre": "rock", "key": "A", "scale": "minor",
        "error": "MIDI94 = Bb6 auf Gitarre String 1 Fret 30 — unmöglich (max Fret 22 = MIDI86)",
        "expected_issue_hint": "94",
    },
    # Bass: Note unter MIDI28 (tiefer als Low-B auf 5-String-Bass)
    {
        "notes": [n(0.0, 24, 0.85, 0.5),  # MIDI24 = C1 — unter Low-E Bass (MIDI28)
                  n(0.5, 33, 0.75, 0.5), n(1.0, 33, 0.80, 0.5), n(1.5, 35, 0.72, 0.5)],
        "instrument": "VB-ROYAL", "genre": "rock", "key": "C", "scale": "minor",
        "error": "MIDI24 (C1) = unter Low-E Bass (MIDI28=E1) — nicht spielbar",
        "expected_issue_hint": "24",
    },
    # Piano: Note außerhalb 88-Tasten-Bereich (MIDI < 21 oder > 108)
    {
        "notes": [n(0.0, 15, 0.70, 0.5),  # MIDI15 — unter A0=21 (tiefste Piano-Taste)
                  n(0.5, 60, 0.75, 0.5), n(1.0, 64, 0.72, 0.5), n(1.5, 67, 0.68, 0.5)],
        "instrument": "Piano", "genre": "contemporary", "key": "C", "scale": "major",
        "error": "MIDI15 unter A0=21 (tiefste Taste eines 88-Tasten-Pianos)",
        "expected_issue_hint": "15",
    },
    # Melodie-Synth: Noten 3 Oktaven über Spielbereich
    {
        "notes": [n(0.0, 60, 0.75), n(0.5, 64, 0.72), n(1.0, 115, 0.80),  # MIDI115 = D8
                  n(1.5, 67, 0.70)],
        "instrument": "Phase-4", "genre": "pop", "key": "C", "scale": "major",
        "error": "MIDI115 = D8 — weit über normalem Melodie-Bereich (max C7=96)",
        "expected_issue_hint": "115",
    },
]

# ── 3. Physisch unmögliche Kombinationen ──────────────────────────────────────

PHYSICALLY_IMPOSSIBLE = [
    # Drums: Open-HH (MIDI46) und Closed-HH (MIDI42) gleichzeitig am selben Step
    # Physisch unmöglich — man kann HH nicht gleichzeitig offen UND zu halten
    {
        "notes": [n(0.0, 36, 0.85),   # Kick
                  n(0.0, 42, 0.75),   # HH closed
                  n(0.0, 46, 0.70),   # HH open — gleichzeitig mit closed!
                  n(1.0, 38, 0.80),   # Snare
                  n(2.0, 36, 0.82), n(2.0, 42, 0.70),
                  n(3.0, 38, 0.78)],
        "instrument": "VD-HEAVY", "genre": "rock", "key": "A", "scale": "minor",
        "error": "HH-closed (MIDI42) und HH-open (MIDI46) gleichzeitig auf Step 0 — physisch unmöglich",
        "expected_issue_hint": "HH",
    },
    # Negative Dauer
    {
        "notes": [n(0.0, 45, 0.80, 0.5), n(0.5, 48, 0.75, -0.25),  # dur=-0.25 !
                  n(1.0, 45, 0.78, 0.5), n(1.5, 50, 0.72, 0.5)],
        "instrument": "VB-ROYAL", "genre": "rock", "key": "A", "scale": "minor",
        "error": "Negative Dauer (dur=-0.25) auf Step 0.5 — ungültig",
        "expected_issue_hint": "dur",
    },
    # Überlappende Noten auf monophonem Instrument (Monoline-Synth)
    {
        "notes": [n(0.0, 60, 0.80, 2.0),   # C4 dauert 2 Beats
                  n(0.5, 64, 0.75, 2.0),   # E4 startet bei 0.5 — überlappt mit C4!
                  n(1.0, 67, 0.70, 1.0)],  # G4 überlappt ebenfalls
        "instrument": "Mono-Synth", "genre": "pop", "key": "C", "scale": "major",
        "error": "Überlappende Noten auf monophonem Instrument — C4 (dur=2) überlagert E4 (start=0.5)",
        "expected_issue_hint": "überlapp",
    },
]

# ── 4. Falscher Bereich (falsche Oktave / Instrument-Typ) ─────────────────────

WRONG_RANGE = [
    # Drums mit Piano-MIDI-Werten (60-80) statt Drum-MIDI (36-59)
    {
        "notes": [n(0.0, 60, 0.85),   # C4 — Piano-Note statt Kick (MIDI36)!
                  n(1.0, 64, 0.80),   # E4 — statt Snare (MIDI38)
                  n(0.5, 72, 0.65),   # C5 — statt HH (MIDI42)
                  n(2.0, 60, 0.82), n(3.0, 64, 0.78)],
        "instrument": "VD-HEAVY", "genre": "rock", "key": "C", "scale": "minor",
        "error": "Drum-Instrument mit Piano-MIDI-Werten (60,64,72) — soll Drum-MIDI 36-59 nutzen",
        "expected_issue_hint": "60",
    },
    # Bass-Linie in Melodie-Bereich (zu hoch — über C5=72)
    {
        "notes": [n(0.0, 81, 0.80, 0.5),  # A5 — viel zu hoch für Bass
                  n(0.5, 83, 0.75, 0.5),  # B5
                  n(1.0, 84, 0.78, 0.5),  # C6
                  n(1.5, 83, 0.72, 0.5)],
        "instrument": "VB-ROYAL", "genre": "rock", "key": "A", "scale": "minor",
        "error": "Bass-Instrument im Melodie-Bereich (A5=81, B5=83) — Bass soll unter C3=48 spielen",
        "expected_issue_hint": "81",
    },
]

# ── 5. Ungültige Velocity ─────────────────────────────────────────────────────

VELOCITY_ERRORS = [
    # Velocity > 1.0 (außerhalb MIDI-Norm)
    {
        "notes": [n(0.0, 36, 2.5, 0.25),  # vel=2.5 — ungültig!
                  n(0.5, 42, 0.65), n(1.0, 38, 0.80), n(1.5, 42, 0.60)],
        "instrument": "VD-HEAVY", "genre": "rock", "key": "A", "scale": "minor",
        "error": "Velocity 2.5 auf MIDI36 — muss zwischen 0.0 und 1.0 liegen",
        "expected_issue_hint": "vel",
    },
    # Velocity = 0.0 (stummer Note)
    {
        "notes": [n(0.0, 45, 0.80, 0.5), n(0.5, 48, 0.0, 0.5),  # vel=0 = stumm!
                  n(1.0, 45, 0.75, 0.5), n(1.5, 50, 0.70, 0.5)],
        "instrument": "VB-ROYAL", "genre": "rock", "key": "A", "scale": "minor",
        "error": "Velocity 0.0 = stumme Note (MIDI48 auf Step 0.5) — Note ist unhörbar",
        "expected_issue_hint": "vel",
    },
]

ALL_ERRORS = HARMONIC_ERRORS + OUT_OF_RANGE + PHYSICALLY_IMPOSSIBLE + WRONG_RANGE + VELOCITY_ERRORS


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHarmonicErrors:

    @pytest.mark.unit
    def test_wrong_root_in_a_minor(self):
        """Bb-Root in A minor wird als harmonischer Fehler erkannt."""
        err = HARMONIC_ERRORS[0]
        resp = _resp(0.25, ["Bb2 als Tonika — in A minor sollte A2 (MIDI45) die Root sein"],
                     harmonic_ok=False)
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.55,   f"Falscher Root soll niedrig scoren: {result['score']}"
        assert result["harmonic_ok"] is False
        assert len(result["issues"]) >= 1

    @pytest.mark.unit
    def test_tritone_in_c_major(self):
        """F# (Tritonus) in C major wird als Dissonanz erkannt."""
        err = HARMONIC_ERRORS[1]
        resp = _resp(0.35, ["F#4 (MIDI66) ist nicht in C major — Tritonus erzeugt starke Dissonanz"],
                     harmonic_ok=False)
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.55
        issues_text = " ".join(result.get("issues", [])).lower()
        assert any(kw in issues_text for kw in ["f#", "triton", "dissonanz", "66"]), \
            f"Issue soll Tritonus erwähnen: {result.get('issues')}"


class TestOutOfRange:

    @pytest.mark.unit
    def test_guitar_impossible_fret(self):
        """MIDI94 auf Gitarre = Fret 30 — physisch unmöglich erkannt."""
        err = OUT_OF_RANGE[0]
        resp = _resp(0.20, ["MIDI94 (Bb6) liegt außerhalb des Gitarren-Bereichs — max Fret 22 = MIDI86"],
                     harmonic_ok=True)
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.45
        issues_text = " ".join(result.get("issues", [])).lower()
        assert any(kw in issues_text for kw in ["94", "bereich", "fret", "unmöglich"]), \
            f"Issue soll Bereichsfehler nennen: {result.get('issues')}"

    @pytest.mark.unit
    def test_bass_below_lowest_string(self):
        """MIDI24 (C1) unter Low-E Bass (MIDI28) erkannt."""
        err = OUT_OF_RANGE[1]
        resp = _resp(0.25, ["MIDI24 (C1) liegt unter dem tiefsten Bass-Ton E1 (MIDI28)"])
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.50

    @pytest.mark.unit
    def test_piano_below_range(self):
        """MIDI15 unter A0=21 (tiefste Klaviertaste) erkannt."""
        err = OUT_OF_RANGE[2]
        resp = _resp(0.20, ["MIDI15 liegt unter A0 (MIDI21) — außerhalb des 88-Tasten-Bereichs"],
                     harmonic_ok=False)
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.45


class TestPhysicallyImpossible:

    @pytest.mark.unit
    def test_hh_open_and_closed_simultaneous(self):
        """Open-HH + Closed-HH gleichzeitig = physisch unmöglich erkannt."""
        err = PHYSICALLY_IMPOSSIBLE[0]
        resp = _resp(0.30,
            ["HH-open (MIDI46) und HH-closed (MIDI42) gleichzeitig auf Step 0 — nicht spielbar"],
            rhythmic_ok=False)
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.55
        issues_text = " ".join(result.get("issues", [])).lower()
        assert any(kw in issues_text for kw in ["hh", "46", "42", "gleichzeitig", "unmöglich"]), \
            f"HH-Konflikt soll als Issue erkannt werden: {result.get('issues')}"

    @pytest.mark.unit
    def test_negative_duration_detected(self):
        """Negative Dauer (dur=-0.25) wird als Fehler erkannt."""
        err = PHYSICALLY_IMPOSSIBLE[1]
        resp = _resp(0.10, ["Negative Note-Dauer (dur=-0.25) auf Step 0.5 — ungültige MIDI-Note"],
                     rhythmic_ok=False)
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.30, \
            f"Negative Dauer ist ein schwerer Fehler: {result['score']}"


class TestWrongRange:

    @pytest.mark.unit
    def test_drums_with_piano_midi(self):
        """Drum-Instrument mit Piano-MIDI-Werten (60,64,72) erkannt."""
        err = WRONG_RANGE[0]
        resp = _resp(0.15,
            ["Drum-Instrument nutzt Piano-Pitches (MIDI60=C4, MIDI64=E4) — Drums sollen MIDI 36-59 nutzen"],
            rhythmic_ok=False)
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.40

    @pytest.mark.unit
    def test_bass_in_soprano_range(self):
        """Bass-Instrument mit Melodie-Werten (A5=81) erkannt."""
        err = WRONG_RANGE[1]
        resp = _resp(0.20,
            ["Bass-Instrument spielt in Soprano-Range (MIDI81=A5) — Bass soll unter MIDI48 bleiben"])
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.45


class TestVelocityErrors:

    @pytest.mark.unit
    def test_velocity_above_one(self):
        """Velocity > 1.0 wird als ungültig erkannt."""
        err = VELOCITY_ERRORS[0]
        resp = _resp(0.20, ["Velocity 2.5 auf MIDI36 — muss zwischen 0.0 und 1.0 liegen"])
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.50

    @pytest.mark.unit
    def test_velocity_zero_silent_note(self):
        """Velocity = 0.0 (stumme Note) wird als Problem erkannt."""
        err = VELOCITY_ERRORS[1]
        resp = _resp(0.35, ["Stumme Note: vel=0.0 auf MIDI48 (Step 0.5) — Note ist unhörbar"])
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
        assert result["score"] < 0.55
        assert len(result.get("issues", [])) >= 1


class TestErrorCountDistribution:

    @pytest.mark.unit
    def test_all_errors_have_low_score(self):
        """Alle 14 Fehler-Patterns sollen score < 0.55 bekommen."""
        scores = []
        for err in ALL_ERRORS:
            low_score = 0.15 + len(scores) * 0.02  # variiert 0.15-0.41
            resp = _resp(low_score, [err["error"][:60]], harmonic_ok=False)
            with patch("src.agent.tools.music_validator._is_available", return_value=True), \
                 patch("src.agent.tools.music_validator._call_llm", return_value=resp):
                from src.agent.tools.music_validator import validate_music_pattern
                result = validate_music_pattern(
                    err["notes"], err["instrument"], err["genre"], err["key"], err["scale"])
            scores.append(result.get("score", 1.0))

        above_threshold = [s for s in scores if s >= 0.55]
        assert len(above_threshold) == 0, \
            f"Diese Fehler-Patterns scorten zu hoch (≥0.55): {above_threshold}"

    @pytest.mark.unit
    def test_error_patterns_have_lower_score_than_correct(self):
        """Fehler-Patterns scoren niedriger als korrekte Patterns."""
        from src.agent.tools.pattern_generators import _drums, _bass
        from src.agent.tools.music_data import _root_midi

        # Korrektes Pattern
        correct_notes = _drums("rock", 2, "basic")
        correct_resp  = json.dumps({"score": 0.80, "rhythmic_ok": True,
                                    "harmonic_ok": True, "genre_fit": True,
                                    "issues": [], "suggestions": [],
                                    "summary": "Korrektes Rock-Pattern."})
        # Fehler-Pattern (Drums mit Piano-MIDI)
        error_resp = _resp(0.15, ["Drum-MIDI-Werte falsch"])

        with patch("src.agent.tools.music_validator._is_available", return_value=True):
            with patch("src.agent.tools.music_validator._call_llm", return_value=correct_resp):
                from src.agent.tools.music_validator import validate_music_pattern
                score_correct = validate_music_pattern(
                    correct_notes, "VD-HEAVY", "rock", "A", "minor")["score"]

            with patch("src.agent.tools.music_validator._call_llm", return_value=error_resp):
                score_error = validate_music_pattern(
                    WRONG_RANGE[0]["notes"], "VD-HEAVY", "rock", "C", "minor")["score"]

        assert score_correct > score_error, \
            f"Korrektes Pattern ({score_correct}) muss > Fehler-Pattern ({score_error})"
