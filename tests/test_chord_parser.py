"""Unit Tests: Chordonomicon-Parser und MIDI-Konverter."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.audio.chord_to_bitwig import (
    parse_chord, chord_to_notes, parse_chordonomicon, progression_to_pattern, ROOT
)


# ── parse_chord ───────────────────────────────────────────────────────────────

class TestParseChord:
    """MIDI-Pitches für Akkord-Tokens."""

    @pytest.mark.unit
    @pytest.mark.parametrize("token,expected", [
        ("C",     [48, 52, 55]),   # C3 major
        ("Amin",  [57, 60, 64]),   # A3 minor
        ("F",     [53, 57, 60]),   # F3 major
        ("G",     [55, 59, 62]),   # G3 major
        ("Dmin",  [50, 53, 57]),   # D3 minor
        ("Fsmin", [54, 57, 61]),   # F#3 minor
        ("Csdim", [49, 52, 55]),   # C#3 dim
        ("Gssus2",[56, 58, 63]),   # G#3 sus2
        ("Cmaj7", [48, 52, 55, 59]),# C3 maj7
        ("Am7",   [57, 60, 64, 67]),# A3 m7
        ("G7",    [55, 59, 62, 65]),# G3 dom7
        ("Eb",    [51, 55, 58]),    # Eb3 major (enharmonic)
        ("Bb",    [58, 62, 65]),    # Bb3 major
    ])
    def test_chord_pitches(self, token, expected):
        assert chord_to_notes(token, octave_shift=0) == expected, \
            f"{token}: erwartet {expected}"

    @pytest.mark.unit
    def test_octave_shift(self):
        base = chord_to_notes("C", octave_shift=0)
        shifted = chord_to_notes("C", octave_shift=1)
        assert all(s == b + 12 for s, b in zip(shifted, base))

    @pytest.mark.unit
    def test_invalid_token_returns_empty(self):
        assert chord_to_notes("XYZ") == []

    @pytest.mark.unit
    def test_parse_chord_returns_root_and_intervals(self):
        result = parse_chord("Amin")
        assert result is not None
        root, intervals = result
        assert root == ROOT["A"]
        assert intervals == [0, 3, 7]

    @pytest.mark.unit
    def test_all_root_notes_present(self):
        for note in ["C","D","E","F","G","A","B"]:
            result = parse_chord(note)
            assert result is not None, f"{note} konnte nicht geparst werden"


# ── parse_chordonomicon ───────────────────────────────────────────────────────

class TestParseChordonomicon:
    """Chordonomicon-Format Parsing."""

    @pytest.mark.unit
    def test_basic_parsing(self):
        text = "Genre: pop | Chords: <verse_1> Amin F G Amin | Decade: 2020.0"
        result = parse_chordonomicon(text)
        assert result["genre"] == "pop"
        assert result["decade"] == 2020.0
        assert "verse_1" in result["sections"]
        assert result["sections"]["verse_1"] == ["Amin", "F", "G", "Amin"]

    @pytest.mark.unit
    def test_multiple_sections(self):
        text = "Genre: rock | Chords: <verse_1> Am Dm <chorus_1> G E Am | Decade: 2010.0"
        result = parse_chordonomicon(text)
        assert "verse_1" in result["sections"]
        assert "chorus_1" in result["sections"]

    @pytest.mark.unit
    def test_missing_sections_tag(self):
        text = "Genre: jazz | Chords: Cmaj7 Am7 Dm7 G7 | Decade: 1960.0"
        result = parse_chordonomicon(text)
        assert result["genre"] == "jazz"

    @pytest.mark.unit
    def test_decade_parsing(self):
        text = "Genre: pop | Chords: <verse_1> C G | Decade: 2023.0"
        result = parse_chordonomicon(text)
        assert result["decade"] == 2023.0


# ── progression_to_pattern ────────────────────────────────────────────────────

class TestProgressionToPattern:
    """MIDI-Pattern-Generierung aus Akkordfolgen."""

    @pytest.mark.unit
    def test_basic_pattern_structure(self):
        pat = progression_to_pattern(["Amin", "F", "G", "Amin"], beats_per_chord=2.0)
        assert "bass" in pat
        assert "chords" in pat
        assert "length_beats" in pat
        assert pat["length_beats"] == 8.0

    @pytest.mark.unit
    def test_bass_notes_count(self):
        # 4 Akkorde × (1 root + 1 fill) = 8 Bass-Noten
        pat = progression_to_pattern(["C", "Am", "F", "G"], beats_per_chord=2.0)
        assert len(pat["bass"]) > 0
        assert len(pat["bass"]) <= 12

    @pytest.mark.unit
    def test_chord_notes_count(self):
        # 4 Akkorde × 3 Töne × 2 (Downbeat + Antizipation) = 24 Chord-Noten
        pat = progression_to_pattern(["C", "Am", "F", "G"], beats_per_chord=2.0)
        assert len(pat["chords"]) == 24

    @pytest.mark.unit
    def test_note_positions_within_clip(self):
        length = 8.0
        pat = progression_to_pattern(["C", "Am", "F", "G"], beats_per_chord=2.0)
        for n in pat["bass"] + pat["chords"]:
            assert 0 <= n["step"] < length, f"Note außerhalb Clip: {n}"
            assert n["dur"] > 0
            assert 0 < n["vel"] <= 1.0

    @pytest.mark.unit
    def test_pitch_range_valid(self):
        pat = progression_to_pattern(["Amin", "F", "G", "Amin"])
        for n in pat["bass"] + pat["chords"]:
            assert 0 <= int(n["pitch"]) <= 127, f"Ungültiger Pitch: {n['pitch']}"

    @pytest.mark.unit
    def test_single_chord(self):
        pat = progression_to_pattern(["C"])
        assert pat["length_beats"] == 2.0
        # C major = 3 Töne, kein Antizipations-Hit bei 1 Akkord (beats_per_chord=2 aber kein Upbeat wenn nur 1 Akkord)
        assert len(pat["chords"]) >= 3  # mindestens 3 Töne (Downbeat)
