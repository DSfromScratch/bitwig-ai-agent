"""Tests für validate_notes (pattern_raw_tool) und generate_pattern (Fallback-Modus)."""
from __future__ import annotations

import os
import pytest

from src.agent.tools.music.pattern_raw_tool import validate_notes

pytestmark = pytest.mark.unit


# ── validate_notes ────────────────────────────────────────────────────────────

class TestValidateNotes:
    """Normalisierung und Validierung von MIDI-Noten."""

    def test_step_key_accepted(self):
        notes = [{"step": 0.0, "pitch": 60, "velocity": 80, "dur": 0.25}]
        result = validate_notes(notes, 8.0)
        assert len(result) == 1
        assert result[0]["step"] == 0.0

    def test_start_key_normalized_to_step(self):
        """Legacy-Format mit 'start' statt 'step' muss akzeptiert und normalisiert werden."""
        notes = [{"start": 1.0, "pitch": 60, "velocity": 80, "dur": 0.5}]
        result = validate_notes(notes, 8.0)
        assert len(result) == 1
        assert result[0]["step"] == 1.0

    def test_step_takes_priority_over_start(self):
        """Wenn beide vorhanden: 'step' hat Vorrang."""
        notes = [{"step": 2.0, "start": 0.0, "pitch": 60, "velocity": 80, "dur": 0.25}]
        result = validate_notes(notes, 8.0)
        assert result[0]["step"] == 2.0

    def test_duration_key_accepted(self):
        notes = [{"step": 0.0, "pitch": 60, "velocity": 80, "duration": 1.0}]
        result = validate_notes(notes, 8.0)
        assert len(result) == 1
        assert result[0]["dur"] == 1.0

    def test_dur_takes_priority_over_duration(self):
        notes = [{"step": 0.0, "pitch": 60, "velocity": 80, "dur": 0.5, "duration": 1.0}]
        result = validate_notes(notes, 8.0)
        assert result[0]["dur"] == 0.5

    def test_velocity_int_direct(self):
        notes = [{"step": 0.0, "pitch": 60, "velocity": 100, "dur": 0.25}]
        result = validate_notes(notes, 8.0)
        assert result[0]["velocity"] == 100

    def test_vel_float_converted(self):
        """vel=0.8 (float 0-1) → velocity=101 (int 0-127)."""
        notes = [{"step": 0.0, "pitch": 60, "vel": 0.8, "dur": 0.25}]
        result = validate_notes(notes, 8.0)
        assert result[0]["velocity"] == int(0.8 * 127)

    def test_vel_default_used_when_neither_present(self):
        """Kein velocity / vel → Default 0.8 → int(0.8*127)=101."""
        notes = [{"step": 0.0, "pitch": 60, "dur": 0.25}]
        result = validate_notes(notes, 8.0)
        assert result[0]["velocity"] == int(0.8 * 127)

    def test_velocity_clamped_to_min_1(self):
        notes = [{"step": 0.0, "pitch": 60, "velocity": 0, "dur": 0.25}]
        result = validate_notes(notes, 8.0)
        assert result[0]["velocity"] == 1

    def test_velocity_clamped_to_max_127(self):
        notes = [{"step": 0.0, "pitch": 60, "velocity": 200, "dur": 0.25}]
        result = validate_notes(notes, 8.0)
        assert result[0]["velocity"] == 127

    def test_note_at_beat_boundary_rejected(self):
        """step >= length_beats → invalid."""
        notes = [{"step": 8.0, "pitch": 60, "velocity": 80, "dur": 0.25}]
        assert validate_notes(notes, 8.0) == []

    def test_negative_step_rejected(self):
        notes = [{"step": -0.1, "pitch": 60, "velocity": 80, "dur": 0.25}]
        assert validate_notes(notes, 8.0) == []

    def test_invalid_pitch_rejected(self):
        assert validate_notes([{"step": 0.0, "pitch": 128, "velocity": 80, "dur": 0.25}], 8.0) == []
        assert validate_notes([{"step": 0.0, "pitch": -1, "velocity": 80, "dur": 0.25}], 8.0) == []

    def test_zero_duration_rejected(self):
        assert validate_notes([{"step": 0.0, "pitch": 60, "velocity": 80, "dur": 0.0}], 8.0) == []

    def test_non_dict_entries_skipped(self):
        notes = [None, "bad", 42, {"step": 0.0, "pitch": 60, "velocity": 80, "dur": 0.25}]
        result = validate_notes(notes, 8.0)
        assert len(result) == 1

    def test_empty_list_returns_empty(self):
        assert validate_notes([], 8.0) == []

    def test_none_returns_empty(self):
        assert validate_notes(None, 8.0) == []

    def test_output_shape(self):
        """Ausgabe enthält genau step, pitch, velocity, dur — nichts anderes."""
        notes = [{"start": 1.0, "pitch": 48, "vel": 0.6, "duration": 0.5, "extra": "ignored"}]
        result = validate_notes(notes, 8.0)
        assert set(result[0].keys()) == {"step", "pitch", "velocity", "dur"}


# ── generate_pattern (Fallback-Modus) ────────────────────────────────────────

class TestGeneratePatternFallback:
    """generate_pattern im FAST_PATTERN_MODE=1 — kein LLM-Aufruf, deterministischer Pfad."""

    def test_fallback_mode_returns_success_string(self, monkeypatch):
        monkeypatch.setenv("FAST_PATTERN_MODE", "1")
        monkeypatch.setattr(
            "src.bitwig_executor.compose_notes",
            lambda payload: "OK: 8 notes written",
        )
        from src.agent.tools.music.pattern_llm_tool import generate_pattern
        result = generate_pattern.invoke({
            "track_index": 1,
            "instrument": "drums",
            "genre": "techno",
            "key": "C",
            "scale": "minor",
            "bars": 2,
            "bpm": 130,
        })
        assert "fallback" in result
        assert "OK" in result

    def test_fallback_mode_uses_deterministic_notes(self, monkeypatch):
        monkeypatch.setenv("FAST_PATTERN_MODE", "1")
        captured = {}

        def _fake_compose(payload):
            captured["notes"] = payload["steps"][0]["args"]["notes"]
            return "OK"

        monkeypatch.setattr("src.bitwig_executor.compose_notes", _fake_compose)
        from src.agent.tools.music.pattern_llm_tool import generate_pattern
        generate_pattern.invoke({
            "track_index": 1, "instrument": "bass", "genre": "house",
            "key": "C", "scale": "minor", "bars": 1, "bpm": 120,
        })
        notes = captured["notes"]
        assert isinstance(notes, list)
        assert len(notes) > 0
        # Alle Noten haben das normalisierte Format
        for n in notes:
            assert "step" in n and "pitch" in n and "velocity" in n and "dur" in n

    def test_fallback_uses_write_notes_step_type(self, monkeypatch):
        monkeypatch.setenv("FAST_PATTERN_MODE", "1")
        captured = {}

        def _fake_compose(payload):
            captured["payload"] = payload
            return "OK"

        monkeypatch.setattr("src.bitwig_executor.compose_notes", _fake_compose)
        from src.agent.tools.music.pattern_llm_tool import generate_pattern
        generate_pattern.invoke({
            "track_index": 2, "instrument": "melody", "genre": "jazz",
            "key": "F", "scale": "major", "bars": 2, "bpm": 100,
        })
        step = captured["payload"]["steps"][0]
        assert step["type"] == "write_notes"
        assert step["args"]["track_index"] == 2

    def test_llm_fallback_when_llm_raises(self, monkeypatch):
        """Wenn LLM fehlschlägt → deterministische Fallback-Noten."""
        monkeypatch.delenv("FAST_PATTERN_MODE", raising=False)
        monkeypatch.setattr(
            "src.agent.tools.music.pattern_llm_tool._generate_notes_via_llm",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "src.agent.tools.music.pattern_llm_tool._fetch_theory_context",
            lambda *a, **kw: "",
        )
        monkeypatch.setattr("src.bitwig_executor.compose_notes", lambda p: "OK fallback")

        from src.agent.tools.music.pattern_llm_tool import generate_pattern
        result = generate_pattern.invoke({
            "track_index": 1, "instrument": "drums", "genre": "techno",
            "key": "C", "scale": "minor", "bars": 2, "bpm": 130,
        })
        assert "fallback" in result
