"""Unit Tests: Automatische Melodie-Generierung."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.audio.chord_to_bitwig import detect_key, generate_melody, PENTATONIC


class TestDetectKey:

    @pytest.mark.unit
    @pytest.mark.parametrize("chords,expected_mode", [
        (["Amin", "F", "G", "Amin"], "minor"),
        (["Dmin", "E", "Amin", "Dmin"], "minor"),
        (["C", "G", "Am", "F"], "major"),   # Mehr Dur-Akkorde
        (["C", "F", "G", "C"], "major"),
    ])
    def test_mode_detection(self, chords, expected_mode):
        _, mode = detect_key(chords)
        assert mode == expected_mode

    @pytest.mark.unit
    def test_minor_root_from_first_minor(self):
        root, mode = detect_key(["Amin", "F", "G", "Amin"])
        assert mode == "minor"
        # Root sollte A sein (MIDI 57 = A3)
        from src.audio.chord_to_bitwig import ROOT
        assert root == ROOT["A"]

    @pytest.mark.unit
    def test_fallback_on_empty(self):
        root, mode = detect_key([])
        assert root is not None
        assert mode in ("minor", "major")

    @pytest.mark.unit
    def test_fallback_on_invalid(self):
        root, mode = detect_key(["XXXINVALID"])
        assert root is not None


class TestGenerateMelody:

    @pytest.mark.unit
    def test_returns_notes_list(self):
        notes = generate_melody(["Amin", "F", "G", "Amin"], length_beats=8.0)
        assert isinstance(notes, list)
        assert len(notes) > 0

    @pytest.mark.unit
    def test_notes_within_clip_length(self):
        length = 8.0
        notes = generate_melody(["Amin", "F", "G", "Amin"], length_beats=length)
        for n in notes:
            assert n["step"] >= 0
            assert n["step"] < length
            assert n["step"] + n["dur"] <= length + 0.1

    @pytest.mark.unit
    def test_pitches_in_valid_range(self):
        notes = generate_melody(["C", "G", "Am", "F"], length_beats=8.0)
        for n in notes:
            assert 0 <= n["pitch"] <= 127, f"Pitch {n['pitch']} außerhalb 0-127"

    @pytest.mark.unit
    def test_velocities_in_valid_range(self):
        notes = generate_melody(["Amin", "F", "G", "Amin"])
        for n in notes:
            assert 0.0 < n["vel"] <= 1.0

    @pytest.mark.unit
    def test_durations_positive(self):
        notes = generate_melody(["Amin", "F", "G", "Amin"])
        for n in notes:
            assert n["dur"] > 0

    @pytest.mark.unit
    def test_pentatonic_scale_used(self):
        """Alle Melodie-Noten müssen in der pentatonischen Skala liegen."""
        chords = ["Amin", "F", "G", "Amin"]
        root, mode = detect_key(chords)
        scale_intervals = PENTATONIC[mode]
        scale_pitches = set()
        for octave in range(8):
            for interval in scale_intervals:
                scale_pitches.add((root + octave * 12 + interval) % 128)

        notes = generate_melody(chords)
        for n in notes:
            assert n["pitch"] % 128 in scale_pitches or \
                   n["pitch"] % 12 in {s % 12 for s in scale_pitches}, \
                   f"Pitch {n['pitch']} nicht in Pentatonik"

    @pytest.mark.unit
    def test_reproducible_with_same_seed(self):
        chords = ["Amin", "F", "G", "Amin"]
        notes1 = generate_melody(chords, seed=42)
        notes2 = generate_melody(chords, seed=42)
        assert notes1 == notes2

    @pytest.mark.unit
    def test_different_seeds_give_different_melodies(self):
        chords = ["Amin", "F", "G", "Amin"]
        notes1 = generate_melody(chords, seed=1)
        notes2 = generate_melody(chords, seed=99)
        pitches1 = [n["pitch"] for n in notes1]
        pitches2 = [n["pitch"] for n in notes2]
        assert pitches1 != pitches2

    @pytest.mark.unit
    def test_last_note_is_tonic(self):
        """Letzte Note soll auf der Tonika enden (Auflösung)."""
        chords = ["Amin", "F", "G", "Amin"]
        root, mode = detect_key(chords)
        notes = generate_melody(chords)
        if notes:
            last_pitch = notes[-1]["pitch"]
            # Pitch-Klasse der letzten Note = Root-Pitch-Klasse
            assert last_pitch % 12 == root % 12, \
                f"Letzte Note {last_pitch} endet nicht auf Tonika {root}"

    @pytest.mark.unit
    @pytest.mark.parametrize("length", [4.0, 8.0, 16.0])
    def test_various_lengths(self, length):
        notes = generate_melody(["Am", "F", "G", "Am"], length_beats=length)
        assert len(notes) > 0
        total_duration = sum(n["dur"] for n in notes)
        assert total_duration <= length + 0.1

    @pytest.mark.unit
    def test_melody_has_variety(self):
        """Melodie soll verschiedene Pitches haben (nicht monoton)."""
        notes = generate_melody(["Amin", "F", "G", "Amin"], length_beats=8.0)
        unique_pitches = len(set(n["pitch"] for n in notes))
        assert unique_pitches >= 3, f"Melodie zu monoton: nur {unique_pitches} verschiedene Töne"

    @pytest.mark.unit
    def test_melody_integrated_in_song_tools(self):
        """generate_melody wird in create_song_from_genre importiert."""
        import inspect
        from src.agent.tools import song_tools
        src = inspect.getsource(song_tools.create_song_from_genre.func)
        assert "generate_melody" in src
        assert "track_indices[5]" in src
