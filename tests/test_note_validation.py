"""Unit Tests: MIDI-Notenvalidierung und write_notes_to_clip."""
import json
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestMidiNoteNames:
    """MIDI-Pitch zu Notenname Konvertierung."""

    NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

    def midi_to_name(self, midi: int) -> str:
        # Bitwig-Konvention: C3=MIDI60, eine Oktave tiefer als Standard (C4=MIDI60)
        octave = (midi // 12) - 2
        return f"{self.NOTE_NAMES[midi % 12]}{octave}"

    @pytest.mark.unit
    @pytest.mark.parametrize("midi,expected", [
        (60, "C3"),   # Bitwig Middle C
        (69, "A3"),   # A440 in Bitwig
        (48, "C2"),
        (72, "C4"),
        (36, "C1"),   # Kick drum
        (38, "D1"),   # Snare
        (42, "F#1"),  # HiHat
        (76, "E4"),   # E5 Standard = E4 Bitwig
        (82, "A#4"),  # War FALSCH als "E5" (Smoke on the Water Bug)
    ])
    def test_midi_to_bitwig_name(self, midi, expected):
        assert self.midi_to_name(midi) == expected

    @pytest.mark.unit
    def test_smoke_on_water_bug(self):
        """E5 = MIDI 76, NICHT 82. 82 = Bb5/A#5 (Halluzinations-Bug)."""
        assert self.midi_to_name(76) == "E4"   # E5 in standard = E4 in Bitwig
        assert self.midi_to_name(82) == "A#4"  # Nicht E5!
        assert self.midi_to_name(82) != "E5"

    @pytest.mark.unit
    def test_smoke_on_water_riff_pitches(self):
        """Smoke on the Water Riff: G4-Bb4-C5 in Bitwig."""
        riff = [67, 70, 72]  # G3, Bb3, C4 in Bitwig (= G4,Bb4,C5 Standard)
        names = [self.midi_to_name(p) for p in riff]
        assert names == ["G3", "A#3", "C4"]


class TestNoteValidation:
    """Validierungslogik aus write_notes_to_clip."""

    @pytest.mark.unit
    def test_valid_notes_pass(self):
        notes = [
            {"step": 0, "pitch": 60, "vel": 0.8, "dur": 1.0},
            {"step": 1, "pitch": 67, "vel": 0.7, "dur": 0.5},
        ]
        errors = self._validate(notes, length_beats=8.0)
        assert errors == []

    @pytest.mark.unit
    def test_pitch_out_of_range(self):
        notes = [{"step": 0, "pitch": 130, "vel": 0.8, "dur": 1.0}]
        errors = self._validate(notes)
        assert any("130" in e for e in errors)

    @pytest.mark.unit
    def test_negative_pitch(self):
        notes = [{"step": 0, "pitch": -1, "vel": 0.8, "dur": 1.0}]
        errors = self._validate(notes)
        assert len(errors) > 0

    @pytest.mark.unit
    def test_step_beyond_clip(self):
        notes = [{"step": 10.0, "pitch": 60, "vel": 0.8, "dur": 1.0}]
        errors = self._validate(notes, length_beats=8.0)
        assert len(errors) > 0  # step 10 > length 8

    @pytest.mark.unit
    def test_zero_duration_skipped(self):
        notes = [{"step": 0, "pitch": 60, "vel": 0.8, "dur": 0}]
        errors = self._validate(notes)
        assert len(errors) > 0

    def _validate(self, notes, length_beats=16.0):
        errors = []
        for i, n in enumerate(notes):
            pitch = int(n.get("pitch", -1))
            step = float(n.get("step", 0))
            dur = float(n.get("dur", 1.0))
            if not (0 <= pitch <= 127):
                errors.append(f"Note {i}: pitch={pitch} ungültig")
            if dur <= 0:
                errors.append(f"Note {i}: dur={dur} ≤ 0")
            if step < 0 or step >= length_beats:
                errors.append(f"Note {i}: step={step} außerhalb ({length_beats})")
        return errors


class TestJsonRepair:
    """JSON-Truncation Reparatur für write_notes_to_clip."""

    @pytest.mark.unit
    def test_valid_json_unchanged(self):
        valid = '[{"step":0,"pitch":60,"vel":0.8,"dur":1.0}]'
        result = self._repair(valid)
        assert result == json.loads(valid)

    @pytest.mark.unit
    def test_truncated_json_repaired(self):
        truncated = '[{"step":0,"pitch":60,"vel":0.8,"dur":1.0},{"step":1,"pitch":62,"vel":0.8'
        result = self._repair(truncated)
        assert result is not None
        assert len(result) >= 1  # Mindestens die erste Note gerettet
        assert result[0]["pitch"] == 60

    @pytest.mark.unit
    def test_empty_truncated_returns_none(self):
        result = self._repair("[{")
        assert result is None or result == []

    def _repair(self, notes_json: str):
        try:
            return json.loads(notes_json)
        except json.JSONDecodeError:
            try:
                trimmed = notes_json[:notes_json.rfind("}") + 1] + "]"
                return json.loads(trimmed)
            except:
                return None
