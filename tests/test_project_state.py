"""Smoke Tests: BitwigProjectState — State Machine.

Testet ohne OSC-Verbindung:
  - Initialisierung (empty / from_bitwig mit gemockter OSC-Antwort)
  - Lesende Abfragen: track_exists, get_track, total_notes, missing_tracks_for
  - Mutations: apply_step für alle Step-Typen
  - Precondition-Szenarien: auto-inject Sequenz aus execute_result
  - Robustheit: leere/fehlerhafte Eingaben
"""
import sys
import os
import struct
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.agent.project_state import BitwigProjectState, TrackState, ClipState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _osc_int_string_packet(address: str, int_val: int, str_val: str) -> bytes:
    """Baut ein minimales OSC-Paket mit (int, string) Argumenten (RFC-konform)."""
    def _pad(b: bytes) -> bytes:
        rem = len(b) % 4
        return b + (b"\x00" * (4 - rem)) if rem else b  # kein Extra-Pad wenn 4-aligned

    addr_bytes = _pad((address + "\x00").encode())
    tag_bytes  = _pad(b",is\x00")
    int_bytes  = struct.pack(">i", int_val)
    str_bytes  = _pad((str_val + "\x00").encode())
    return addr_bytes + tag_bytes + int_bytes + str_bytes


def _make_state(*track_names: str) -> BitwigProjectState:
    tracks = [TrackState(index=i + 1, name=n) for i, n in enumerate(track_names)]
    return BitwigProjectState(tracks=tracks, tempo=120.0)


# ── Initialisierung ───────────────────────────────────────────────────────────

class TestInit:

    @pytest.mark.unit
    def test_empty_state(self):
        s = BitwigProjectState.empty()
        assert s.track_count() == 0
        assert s.tempo == 120.0
        assert s.total_notes() == 0

    @pytest.mark.unit
    def test_from_bitwig_no_osc(self):
        """Wenn OSC nicht erreichbar → leere Track-Liste, kein Crash."""
        from unittest.mock import patch
        with patch.object(BitwigProjectState, "_query", return_value=None):
            s = BitwigProjectState.from_bitwig()
        assert isinstance(s, BitwigProjectState)
        assert s.track_count() == 0

    @pytest.mark.unit
    def test_load_tracks_from_osc_packet(self):
        """_load_tracks parst korrektes OSC-Paket."""
        from unittest.mock import patch
        packet = _osc_int_string_packet(
            "/agent/track/count/response", 3, "v9 Kick,v9 Snare,Phase-4"
        )
        with patch.object(BitwigProjectState, "_query", return_value=packet):
            tracks = BitwigProjectState._load_tracks()

        assert len(tracks) == 3
        assert tracks[0].name == "v9 Kick"
        assert tracks[1].name == "v9 Snare"
        assert tracks[2].name == "Phase-4"
        assert tracks[0].index == 1
        assert tracks[2].index == 3

    @pytest.mark.unit
    def test_load_tracks_empty_response(self):
        """Kein Crash wenn Bitwig 0 Tracks meldet."""
        from unittest.mock import patch
        packet = _osc_int_string_packet("/agent/track/count/response", 0, "")
        with patch.object(BitwigProjectState, "_query", return_value=packet):
            tracks = BitwigProjectState._load_tracks()
        assert tracks == []

    @pytest.mark.unit
    def test_load_tracks_osc_none(self):
        from unittest.mock import patch
        with patch.object(BitwigProjectState, "_query", return_value=None):
            tracks = BitwigProjectState._load_tracks()
        assert tracks == []

    @pytest.mark.unit
    def test_from_bitwig_merges_note_counts(self):
        """from_bitwig trägt Note-Counts in TrackState.clips ein."""
        from unittest.mock import patch
        packet = _osc_int_string_packet(
            "/agent/track/count/response", 2, "v9 Kick,FM-4"
        )
        with patch.object(BitwigProjectState, "_query", return_value=packet), \
             patch.object(BitwigProjectState, "_load_note_counts",
                          return_value={"v9 Kick": 8, "FM-4": 4}):
            s = BitwigProjectState.from_bitwig()

        assert s.get_track(1).note_count(0) == 8
        assert s.get_track(2).note_count(0) == 4
        assert s.total_notes() == 12


# ── Lesende Abfragen ──────────────────────────────────────────────────────────

class TestQueries:

    @pytest.mark.unit
    def test_track_exists(self):
        s = _make_state("Kick", "Snare", "Bass")
        assert s.track_exists(1)
        assert s.track_exists(3)
        assert not s.track_exists(4)
        assert not s.track_exists(0)

    @pytest.mark.unit
    def test_get_track_returns_correct(self):
        s = _make_state("Phase-4", "FM-4")
        t = s.get_track(2)
        assert t is not None
        assert t.name == "FM-4"
        assert t.index == 2

    @pytest.mark.unit
    def test_get_track_missing_returns_none(self):
        s = _make_state("Phase-4")
        assert s.get_track(99) is None

    @pytest.mark.unit
    def test_missing_tracks_for(self):
        s = _make_state("Kick", "Snare")
        assert s.missing_tracks_for(2) == 0   # 2 Tracks, brauche idx 2 → ok
        assert s.missing_tracks_for(3) == 1   # fehlt 1
        assert s.missing_tracks_for(5) == 3   # fehlen 3
        assert s.missing_tracks_for(1) == 0   # idx 1 existiert

    @pytest.mark.unit
    def test_total_notes_sum(self):
        s = _make_state("Kick", "Snare")
        s.get_track(1).clips[0] = ClipState(slot=0, note_count=8)
        s.get_track(2).clips[0] = ClipState(slot=0, note_count=4)
        s.get_track(2).clips[1] = ClipState(slot=1, note_count=2)
        assert s.total_notes() == 14

    @pytest.mark.unit
    def test_repr_contains_track_info(self):
        s = _make_state("Phase-4")
        r = repr(s)
        assert "Phase-4" in r
        assert "BitwigProjectState" in r


# ── apply_step Mutations ──────────────────────────────────────────────────────

class TestApplyStep:

    @pytest.mark.unit
    def test_add_track_appends(self):
        s = BitwigProjectState.empty()
        s.apply_step({"type": "add_track", "args": {"track_type": "instrument"}})
        assert s.track_count() == 1
        assert s.track_exists(1)
        s.apply_step({"type": "add_track", "args": {"track_type": "instrument"}})
        assert s.track_count() == 2
        assert s.track_exists(2)

    @pytest.mark.unit
    def test_add_track_increments_index(self):
        s = _make_state("A", "B", "C")
        s.apply_step({"type": "add_track", "args": {}})
        assert s.get_track(4).name == "Inst 4"

    @pytest.mark.unit
    def test_load_instrument_sets_instrument(self):
        s = _make_state("Inst 1")
        s.apply_step({"type": "load_instrument",
                      "args": {"track_index": 1, "name": "Phase-4"}})
        t = s.get_track(1)
        assert t.has_instrument()
        assert t.instrument == "phase-4"
        assert t.name == "Phase-4"

    @pytest.mark.unit
    def test_load_instrument_on_missing_track_creates_it(self):
        """load_instrument auf nicht-existierenden Track → Track wird angelegt."""
        s = BitwigProjectState.empty()
        s.apply_step({"type": "load_instrument",
                      "args": {"track_index": 3, "name": "FM-4"}})
        t = s.get_track(3)
        assert t is not None
        assert t.has_instrument()

    @pytest.mark.unit
    def test_append_effect_adds_to_fx(self):
        s = _make_state("Phase-4")
        s.apply_step({"type": "append_effect",
                      "args": {"track_index": 1, "name": "Reverb"}})
        s.apply_step({"type": "append_effect",
                      "args": {"track_index": 1, "name": "Delay-2"}})
        assert s.get_track(1).fx == ["reverb", "delay-2"]

    @pytest.mark.unit
    def test_append_effect_on_missing_track_no_crash(self):
        s = BitwigProjectState.empty()
        s.apply_step({"type": "append_effect",
                      "args": {"track_index": 5, "name": "Reverb"}})
        assert s.track_count() == 0  # kein Crash, kein Track angelegt

    @pytest.mark.unit
    def test_write_notes_updates_clip(self):
        s = _make_state("v9 Kick")
        notes = [{"step": i, "pitch": 36, "vel": 1.0, "dur": 0.5} for i in range(8)]
        s.apply_step({"type": "write_notes",
                      "args": {"track_index": 1, "slot": 0, "notes": notes}})
        assert s.get_track(1).note_count(0) == 8
        assert s.total_notes() == 8

    @pytest.mark.unit
    def test_write_notes_multiple_slots(self):
        s = _make_state("Bass")
        s.apply_step({"type": "write_notes",
                      "args": {"track_index": 1, "slot": 0,
                               "notes": [{"step": 0}] * 4}})
        s.apply_step({"type": "write_notes",
                      "args": {"track_index": 1, "slot": 1,
                               "notes": [{"step": 0}] * 4}})
        assert s.get_track(1).note_count(0) == 4
        assert s.get_track(1).note_count(1) == 4
        assert s.total_notes() == 8

    @pytest.mark.unit
    def test_write_notes_on_missing_track_no_crash(self):
        s = BitwigProjectState.empty()
        s.apply_step({"type": "write_notes",
                      "args": {"track_index": 2, "slot": 0, "notes": [1, 2, 3]}})
        assert s.total_notes() == 0

    @pytest.mark.unit
    def test_set_tempo(self):
        s = BitwigProjectState.empty()
        s.apply_step({"type": "set_tempo", "args": {"bpm": 140.0}})
        assert s.tempo == 140.0

    @pytest.mark.unit
    def test_unknown_step_type_no_crash(self):
        s = BitwigProjectState.empty()
        s.apply_step({"type": "play", "args": {}})
        s.apply_step({"type": "stop", "args": {}})
        s.apply_step({"type": "unbekannt_xyz", "args": {}})
        assert s.track_count() == 0

    @pytest.mark.unit
    def test_apply_step_empty_dict(self):
        s = BitwigProjectState.empty()
        s.apply_step({})
        assert s.track_count() == 0


# ── Precondition-Szenarien ────────────────────────────────────────────────────

class TestPreconditionScenarios:
    """Simuliert den execute_result Ablauf mit Precondition-Fehlern."""

    @pytest.mark.unit
    def test_auto_inject_sequence(self):
        """Wenn load_instrument error:precondition:track_not_found:3 bekommt
        → 3 add_track-Steps werden injiziert → Track 3 existiert."""
        s = BitwigProjectState.empty()
        missing = s.missing_tracks_for(3)
        assert missing == 3

        for _ in range(missing):
            s.apply_step({"type": "add_track", "args": {"track_type": "instrument"}})

        assert s.track_count() == 3
        assert s.track_exists(3)
        assert s.missing_tracks_for(3) == 0

    @pytest.mark.unit
    def test_precondition_track_exists_after_add(self):
        """Nach add_track + load_instrument ist Instrument gesetzt."""
        s = BitwigProjectState.empty()
        s.apply_step({"type": "add_track", "args": {}})
        assert s.track_exists(1)
        s.apply_step({"type": "load_instrument",
                      "args": {"track_index": 1, "name": "v9 Kick"}})
        assert s.get_track(1).has_instrument()

    @pytest.mark.unit
    def test_full_setup_sequence(self):
        """Vollständige Setup-Sequenz: 3 Tracks, Instrumente, Noten."""
        s = BitwigProjectState.empty()
        instruments = ["v9 Kick", "v9 Snare", "Phase-4"]
        for name in instruments:
            s.apply_step({"type": "add_track", "args": {}})

        assert s.track_count() == 3

        for i, name in enumerate(instruments, start=1):
            s.apply_step({"type": "load_instrument",
                          "args": {"track_index": i, "name": name}})

        assert all(s.get_track(i).has_instrument() for i in range(1, 4))

        for i in range(1, 4):
            notes = [{"step": j, "pitch": 36} for j in range(8)]
            s.apply_step({"type": "write_notes",
                          "args": {"track_index": i, "slot": 0, "notes": notes}})

        assert s.total_notes() == 24
        assert s.get_track(3).note_count(0) == 8

    @pytest.mark.unit
    def test_missing_tracks_idempotent_when_enough(self):
        s = _make_state("A", "B", "C", "D", "E")
        assert s.missing_tracks_for(1) == 0
        assert s.missing_tracks_for(5) == 0
        assert s.missing_tracks_for(6) == 1

    @pytest.mark.unit
    def test_has_instrument_false_by_default(self):
        s = _make_state("Inst 1")
        assert not s.get_track(1).has_instrument()
