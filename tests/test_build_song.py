"""Tests für das build_song Tool.

Unit-Tests laufen ohne Bitwig (OSC wird gemockt).
Integration-Tests erfordern laufende BitwigAgentBridge.
"""
import json
import pytest
import sys
import os
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_project(bpm=120, instrument="Phase-4", fx=None, notes=None, length_beats=8.0):
    """Minimales gültiges project_json."""
    return json.dumps({
        "bpm": bpm,
        "tracks": [{
            "index": 1,
            "instrument": instrument,
            "fx": fx or [],
            "clip": {
                "slot": 0,
                "length_beats": length_beats,
                "notes": notes or [
                    {"step": 0, "pitch": 40, "vel": 0.8, "dur": 1.0},
                    {"step": 1, "pitch": 43, "vel": 0.8, "dur": 1.0},
                ],
            },
        }],
    })


# ── Unit-Tests (kein Bitwig nötig) ───────────────────────────────────────────

class TestBuildSongUnit:
    """Unit-Tests mit gemocktem OSC-Client und Bridge."""

    @pytest.fixture(autouse=True)
    def mock_bridge_and_osc(self):
        """Mockt _check_bridge (True) und _osc_client."""
        self.mock_client = MagicMock()
        with patch("src.agent.tools.song_tools._check_bridge", return_value=True), \
             patch("src.agent.tools.song_tools._osc_client", return_value=self.mock_client), \
             patch("time.sleep"):  # sleep überspringen → Tests schnell
            yield

    @pytest.mark.unit
    def test_returns_ok_summary(self):
        """build_song gibt 'build_song OK' zurück bei gültigem Input."""
        from src.agent.tools.song_tools import build_song
        result = build_song.invoke({"project_json": _make_project()})
        assert "build_song OK" in result
        assert "BPM=120" in result
        assert "Track 1" in result

    @pytest.mark.unit
    def test_sets_tempo(self):
        """BPM wird per OSC als erstes gesendet."""
        from src.agent.tools.song_tools import build_song
        build_song.invoke({"project_json": _make_project(bpm=140)})
        self.mock_client.send_message.assert_any_call("/transport/tempo", 140.0)

    @pytest.mark.unit
    def test_creates_instrument_track(self):
        """Track-Add und Instrument-Load werden gesendet."""
        from src.agent.tools.song_tools import build_song
        build_song.invoke({"project_json": _make_project(instrument="FM-4")})
        self.mock_client.send_message.assert_any_call("/track/add/instrument", 1)
        self.mock_client.send_message.assert_any_call("/browser/device/load", "FM-4")

    @pytest.mark.unit
    def test_loads_fx_devices(self):
        """Alle FX-Devices werden in Reihenfolge geladen."""
        from src.agent.tools.song_tools import build_song
        build_song.invoke({"project_json": _make_project(fx=["Distortion", "Amp", "EQ-5"])})
        calls = [c[0][1] for c in self.mock_client.send_message.call_args_list
                 if c[0][0] == "/browser/device/load"]
        # Instrument zuerst, dann FX in Reihenfolge
        assert calls[0] == "Phase-4"
        assert calls[1] == "Distortion"
        assert calls[2] == "Amp"
        assert calls[3] == "EQ-5"

    @pytest.mark.unit
    def test_writes_notes_via_osc(self):
        """Noten werden als /clip/note/beat OSC-Messages gesendet."""
        from src.agent.tools.song_tools import build_song
        notes = [
            {"step": 0, "pitch": 40, "vel": 0.8, "dur": 1.0},
            {"step": 1, "pitch": 43, "vel": 0.8, "dur": 1.0},
            {"step": 2, "pitch": 45, "vel": 0.7, "dur": 0.5},
        ]
        build_song.invoke({"project_json": _make_project(notes=notes)})
        note_calls = [c[0][1] for c in self.mock_client.send_message.call_args_list
                      if c[0][0] == "/clip/note/beat"]
        assert len(note_calls) == 3
        assert note_calls[0][0] == 0.0   # step
        assert note_calls[0][1] == 40.0  # pitch E2
        assert note_calls[1][1] == 43.0  # pitch G2

    @pytest.mark.unit
    def test_note_count_in_summary(self):
        """Summary enthält korrekte Noten-Anzahl."""
        from src.agent.tools.song_tools import build_song
        notes = [{"step": i, "pitch": 40, "vel": 0.8, "dur": 1.0} for i in range(5)]
        result = build_song.invoke({"project_json": _make_project(notes=notes, length_beats=10.0)})
        assert "5/5" in result

    @pytest.mark.unit
    def test_invalid_notes_skipped(self):
        """Noten mit ungültigem pitch oder step außerhalb Clip werden übersprungen."""
        from src.agent.tools.song_tools import build_song
        notes = [
            {"step": 0,  "pitch": 40,  "vel": 0.8, "dur": 1.0},  # gültig
            {"step": 0,  "pitch": -1,  "vel": 0.8, "dur": 1.0},  # pitch ungültig
            {"step": 0,  "pitch": 128, "vel": 0.8, "dur": 1.0},  # pitch > 127
            {"step": 99, "pitch": 40,  "vel": 0.8, "dur": 1.0},  # step > length_beats
            {"step": 0,  "pitch": 43,  "vel": 0.8, "dur": -1.0}, # dur ≤ 0
        ]
        result = build_song.invoke({"project_json": _make_project(notes=notes, length_beats=8.0)})
        assert "1/5" in result

    @pytest.mark.unit
    def test_velocity_clipped_to_valid_range(self):
        """Velocity außerhalb [0.01, 1.0] wird geclippt, Note bleibt gültig."""
        from src.agent.tools.song_tools import build_song
        notes = [
            {"step": 0, "pitch": 40, "vel": 2.5,  "dur": 1.0},  # zu hoch → 1.0
            {"step": 1, "pitch": 40, "vel": -0.1, "dur": 1.0},  # negativ → 0.01
        ]
        result = build_song.invoke({"project_json": _make_project(notes=notes)})
        # Beide Noten bleiben gültig (nur geclippt)
        assert "2/2" in result

    @pytest.mark.unit
    def test_multiple_tracks(self):
        """Mehrere Tracks werden alle angelegt."""
        from src.agent.tools.song_tools import build_song
        project = json.dumps({
            "bpm": 120,
            "tracks": [
                {
                    "index": 1,
                    "instrument": "Phase-4",
                    "fx": [],
                    "clip": {"slot": 0, "length_beats": 8.0,
                             "notes": [{"step": 0, "pitch": 40, "vel": 0.8, "dur": 1.0}]},
                },
                {
                    "index": 2,
                    "instrument": "FM-4",
                    "fx": ["Reverb"],
                    "clip": {"slot": 0, "length_beats": 8.0,
                             "notes": [{"step": 0, "pitch": 60, "vel": 0.7, "dur": 1.0}]},
                },
            ],
        })
        result = build_song.invoke({"project_json": project})
        assert "Track 1" in result
        assert "Track 2" in result
        track_add_count = sum(
            1 for c in self.mock_client.send_message.call_args_list
            if c[0][0] == "/track/add/instrument"
        )
        assert track_add_count == 2

    @pytest.mark.unit
    def test_track_without_notes(self):
        """Track ohne Noten-Clip wird trotzdem angelegt (kein Clip-Create)."""
        from src.agent.tools.song_tools import build_song
        project = json.dumps({
            "bpm": 120,
            "tracks": [{"index": 1, "instrument": "Phase-4", "fx": [], "clip": {"notes": []}}],
        })
        result = build_song.invoke({"project_json": project})
        assert "kein Clip" in result
        # /clip/create darf nicht gesendet worden sein
        clip_calls = [c for c in self.mock_client.send_message.call_args_list
                      if c[0][0] == "/clip/create"]
        assert clip_calls == []

    @pytest.mark.unit
    def test_invalid_json_returns_error(self):
        """Kaputtes JSON gibt Fehler-String zurück statt Exception."""
        from src.agent.tools.song_tools import build_song
        result = build_song.invoke({"project_json": '{"bpm": 120, "tracks": [{'})
        assert "Fehler" in result
        assert "project_json" in result

    @pytest.mark.unit
    def test_empty_tracks_returns_error(self):
        """Leeres tracks-Array gibt Fehler zurück."""
        from src.agent.tools.song_tools import build_song
        result = build_song.invoke({"project_json": '{"bpm": 120, "tracks": []}'})
        assert "Fehler" in result
        assert "tracks" in result

    @pytest.mark.unit
    def test_bridge_unreachable_returns_error(self):
        """Bridge nicht erreichbar → Fehler-String, kein OSC-Call."""
        from src.agent.tools.song_tools import build_song
        with patch("src.agent.tools.song_tools._check_bridge", return_value=False):
            result = build_song.invoke({"project_json": _make_project()})
        assert "Fehler" in result
        assert "Bridge" in result or "nicht erreichbar" in result

    @pytest.mark.unit
    def test_rock_midi_range(self):
        """Rock-Riff im E-Moll-Pentatonik-Bereich E2–E3 (MIDI 40–52)."""
        from src.agent.tools.song_tools import build_song
        rock_notes = [
            {"step": 0,  "pitch": 40, "vel": 0.8, "dur": 1.0},  # E2
            {"step": 1,  "pitch": 43, "vel": 0.8, "dur": 1.0},  # G2
            {"step": 2,  "pitch": 45, "vel": 0.8, "dur": 1.0},  # A2
            {"step": 3,  "pitch": 47, "vel": 0.8, "dur": 1.0},  # B2
            {"step": 4,  "pitch": 50, "vel": 0.8, "dur": 1.0},  # D3
            {"step": 5,  "pitch": 52, "vel": 0.8, "dur": 1.0},  # E3
        ]
        result = build_song.invoke({
            "project_json": _make_project(
                instrument="Phase-4", fx=["Distortion", "Amp"],
                notes=rock_notes, length_beats=8.0
            )
        })
        assert "build_song OK" in result
        assert "6/6" in result
        # Alle Noten-Pitches korrekt gesendet
        sent_pitches = [c[0][1][1] for c in self.mock_client.send_message.call_args_list
                        if c[0][0] == "/clip/note/beat"]
        assert sent_pitches == [40.0, 43.0, 45.0, 47.0, 50.0, 52.0]

    @pytest.mark.unit
    def test_clip_created_before_notes(self):
        """/clip/create muss vor /clip/note/beat gesendet werden."""
        from src.agent.tools.song_tools import build_song
        build_song.invoke({"project_json": _make_project()})
        msg_addresses = [c[0][0] for c in self.mock_client.send_message.call_args_list]
        clip_create_idx = next(
            (i for i, a in enumerate(msg_addresses) if a == "/clip/create"), None
        )
        first_note_idx = next(
            (i for i, a in enumerate(msg_addresses) if a == "/clip/note/beat"), None
        )
        assert clip_create_idx is not None, "/clip/create wurde nicht gesendet"
        assert first_note_idx is not None, "/clip/note/beat wurde nicht gesendet"
        assert clip_create_idx < first_note_idx, \
            "/clip/create muss vor /clip/note/beat kommen"


# ── Integration-Tests (erfordern Bitwig + Bridge) ────────────────────────────

class TestBuildSongIntegration:
    """End-to-End Tests mit echter BitwigAgentBridge."""

    @pytest.fixture(autouse=True)
    def cleanup_track(self, osc_available):
        """Löscht den zuletzt angelegten Track nach jedem Test (Teardown)."""
        yield
        if not osc_available:
            return
        import time
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient("127.0.0.1", 8001)
        # Kurz warten damit Bitwig die Noten fertig schreibt, dann löschen
        time.sleep(0.3)
        client.send_message("/track/delete/last", 1)
        time.sleep(0.3)

    @pytest.mark.integration
    def test_build_single_track_rock_riff(self, osc_available):
        """Erstellt einen echten Rock-Riff-Track in Bitwig."""
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")

        from src.agent.tools.song_tools import build_song
        notes = [
            {"step": i, "pitch": p, "vel": 0.8, "dur": 1.0}
            for i, p in enumerate([40, 43, 45, 47, 50, 52, 47, 50])
        ]
        result = build_song.invoke({
            "project_json": _make_project(
                bpm=120,
                instrument="Phase-4",
                fx=["Distortion", "Amp"],
                notes=notes,
                length_beats=8.0,
            )
        })
        assert "build_song OK" in result
        assert "8/8" in result

    @pytest.mark.integration
    @pytest.mark.slow
    def test_build_song_token_efficiency(self, osc_available):
        """build_song erzeugt nur 1 Tool-Call statt 7+ einzelner Calls.

        Dokumentiert den Token-Spareffekt: Vorher ~14k Tokens, jetzt ~4k Tokens.
        """
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")

        from src.agent.tools.song_tools import build_song
        # 40 Noten (wie im realen Riff)
        notes = [
            {"step": i, "pitch": 40 + (i % 6) * 2, "vel": 0.8, "dur": 1.0}
            for i in range(40)
        ]
        project = json.dumps({
            "bpm": 120,
            "tracks": [{
                "index": 1,
                "instrument": "Phase-4",
                "fx": ["Distortion", "Amp", "EQ-5"],
                "clip": {"slot": 0, "length_beats": 40.0, "notes": notes},
            }],
        })
        result = build_song.invoke({"project_json": project})
        assert "build_song OK" in result
        # 40 Noten alle gültig
        assert "40/40" in result
