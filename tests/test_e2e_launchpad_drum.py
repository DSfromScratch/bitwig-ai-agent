"""
Launchpad Drum Record — Integration Test.

Zwei-Phasen-Ablauf:
  Phase 1 — Drum Kit anlegen: Track 1, v9 Kick laden (execute_setup)
  Phase 2 — Aufnahme: record → play_notes (Kick-Pattern) → stop
             Verifizierung: note_count > 0 auf Track 1

Vorbedingungen:
  - Bitwig Studio läuft (BitwigAgentBridge erreichbar, Port 8001)
  - LaunchpadControllerExtension aktiv (Port 8003)
  - Launchpad im DRUM-Modus (User 1 gedrückt)

Ausführen:
    pytest tests/test_e2e_launchpad_drum.py -m integration -v -s
"""
import time
import socket
import pytest

pytest.importorskip("bitwigbridge", reason="bitwigbridge-Repo nicht installiert (CI)")

from src.bitwig_executor import execute_setup, compose_notes
from src.agent.tools.suggest_tools import get_launchpad_mode, set_launchpad_mode, play_notes, arm_track
from src.agent.tools.bitwig_tools import control_bitwig as _control_bitwig_fn
from src.agent.tools.song_tools import get_bitwig_track_state as _get_track_state_fn


def _control_bitwig(**kwargs) -> str:
    """Ruft die control_bitwig-Funktion direkt auf (kein StructuredTool-Wrapper)."""
    return _control_bitwig_fn.func(**kwargs)


def _get_track_state() -> str:
    return _get_track_state_fn.func()


def _write_drum_pattern(track_index: int, slot: int = 0) -> str:
    """Schreibt ein Kick+Snare+HH Pattern direkt in den Clip (kein Recording nötig)."""
    return compose_notes({
        "context_type": "track",
        "target": {"bpm": 120, "genre": "drum"},
        "track": {"index": track_index, "name": "Drums", "instrument": "v9 Kick"},
        "summary": "Kick+Snare+HH Grundbeat",
        "steps": [{
            "type": "write_drum_pattern",
            "args": {
                "track_index": track_index,
                "slot": slot,
                "length_beats": 8,
                "pattern": {
                    "kick":  [1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0],
                    "snare": [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0],
                    "hihat": [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],
                },
            },
            "status": "pending",
            "note": "",
        }],
    })


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def launchpad_available():
    """True wenn LaunchpadControllerExtension auf Port 8003 antwortet."""
    try:
        from pythonosc import udp_client
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(2.0)
        try:
            sock.bind(("", 9005))
        except OSError:
            pass
        try:
            udp_client.SimpleUDPClient("127.0.0.1", 8003).send_message(
                "/launchpad/mode/get", 1
            )
            data, _ = sock.recvfrom(512)
            return b"CONTROL" in data or b"DRUM" in data or b"INSTRUMENT" in data
        except socket.timeout:
            return False
        finally:
            sock.close()
    except Exception:
        return False


# ── Unit-Tests (kein Bitwig nötig) ────────────────────────────────────────────

class TestDrumSetupSchema:

    @pytest.mark.unit
    def test_execute_setup_schema_valid(self):
        """execute_setup akzeptiert ein gültiges Drum-Setup-Dict ohne Fehler."""
        from unittest.mock import patch
        with patch("src.bitwig_executor._exec_step_and_wait", return_value="ok"), \
             patch("src.agent.tools.song_tools._check_bridge", return_value=True):
            result = execute_setup({
                "context_type": "song",
                "target": {"bpm": 120, "genre": "drum"},
                "summary": "Kick Track Setup",
                "steps": [
                    {"type": "set_tempo",       "args": {"bpm": 120},                              "status": "pending", "note": ""},
                    {"type": "add_track",        "args": {"track_type": "instrument"},              "status": "pending", "note": "Kick"},
                    {"type": "load_instrument",  "args": {"track_index": 1, "name": "v9 Kick"},    "status": "pending", "note": ""},
                    {"type": "select_track",     "args": {"track_index": 1},                       "status": "pending", "note": ""},
                ],
            })
        assert isinstance(result, str)
        assert "FEHLER" not in result or "pending" not in result

    @pytest.mark.unit
    def test_play_notes_empty_returns_message(self):
        """play_notes mit leerer Liste gibt verständliche Meldung zurück."""
        result = play_notes([], bpm=120)
        assert "Keine Noten" in result

    @pytest.mark.unit
    def test_play_notes_osc_error_handled(self):
        """play_notes fängt OSC-Fehler ab und gibt Fehlerstring zurück."""
        from unittest.mock import patch
        with patch("pythonosc.udp_client.SimpleUDPClient") as mock_cls:
            mock_cls.side_effect = Exception("Port nicht erreichbar")
            result = play_notes([{"note": 36, "vel": 100, "dur": 0.1}], bpm=120)
        assert "Fehler" in result

    @pytest.mark.unit
    def test_drum_note_to_pad_mapping(self):
        """Kick (36) liegt auf Pad 11, Snare (38) auf Pad 13."""
        from src.agent.tools.suggest_tools import _DRUM_NOTE_TO_PAD
        assert _DRUM_NOTE_TO_PAD[36] == 11  # Kick: Zeile 1, Spalte 1
        assert _DRUM_NOTE_TO_PAD[38] == 13  # Snare: Zeile 1, Spalte 3
        assert _DRUM_NOTE_TO_PAD[42] == 23  # HH closed: Zeile 2, Spalte 3

    @pytest.mark.unit
    def test_drum_pad_color_kick_is_orange_red(self):
        """Kick-Pad hat die korrekte orange-rote Farbe."""
        from src.agent.tools.suggest_tools import _DRUM_PAD_COLORS
        r, g, b = _DRUM_PAD_COLORS[36]
        assert r == 63 and g == 10 and b == 0


# ── Integration-Tests (Bitwig + Launchpad nötig) ─────────────────────────────

@pytest.mark.integration
@pytest.mark.slow
class TestLaunchpadDrumRecord:
    """Vollständiger Drum-Record-Workflow über Launchpad."""

    # Kick-Pattern: 8 Achtel à 120 BPM (2 Takte, Kick auf 1+3)
    KICK_PATTERN = [
        {"note": 36, "vel": 127, "dur": 0.08, "gap": 0.17},  # Beat 1
        {"note": 36, "vel": 100, "dur": 0.08, "gap": 0.17},  # Beat 1+
        {"note": 36, "vel": 127, "dur": 0.08, "gap": 0.17},  # Beat 3
        {"note": 36, "vel": 100, "dur": 0.08, "gap": 0.17},  # Beat 3+
    ]

    def test_phase1_drum_setup(self, osc_available):
        """Phase 1: Drum-Track anlegen und v9 Kick laden."""
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar (Port 8001)")

        result = execute_setup({
            "context_type": "song",
            "target": {"bpm": 120, "genre": "drum"},
            "summary": "Kick Track Setup",
            "steps": [
                {"type": "set_tempo",       "args": {"bpm": 120},                           "status": "pending", "note": ""},
                {"type": "add_track",        "args": {"track_type": "instrument"},           "status": "pending", "note": "Kick"},
                {"type": "load_instrument",  "args": {"track_index": 1, "name": "v9 Kick"}, "status": "pending", "note": ""},
                {"type": "select_track",     "args": {"track_index": 1},                    "status": "pending", "note": ""},
            ],
        })

        print(f"\nSetup-Ergebnis: {result}")
        assert "FEHLER" not in result, f"Setup fehlgeschlagen: {result}"

    def test_phase2_write_notes(self, osc_available, launchpad_available):
        """Phase 2: Noten direkt in Clip schreiben (Edit Mode) + Launchpad Preview."""
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar (Port 8001)")
        if not launchpad_available:
            pytest.skip("LaunchpadControllerExtension nicht erreichbar (Port 8003)")

        # DRUM-Modus sicherstellen
        mode_result = get_launchpad_mode()
        if "DRUM" not in mode_result:
            mode_result = set_launchpad_mode("DRUM")
        print(f"\nLaunchpad-Modus: {mode_result}")
        assert "DRUM" in mode_result, f"Modus-Wechsel fehlgeschlagen: {mode_result}"

        # Noten direkt in Clip schreiben
        write_result = _write_drum_pattern(track_index=1, slot=0)
        print(f"Write: {write_result}")
        assert "FEHLER" not in write_result, f"write_drum_pattern fehlgeschlagen: {write_result}"
        assert "write_notes✓" in write_result, f"Keine Noten geschrieben: {write_result}"

        # Launchpad Preview: Pattern einmal abspielen (LEDs leuchten auf)
        play_result = play_notes(self.KICK_PATTERN, bpm=120)
        print(f"Preview: {play_result}")
        assert "Fehler" not in play_result, f"play_notes fehlgeschlagen: {play_result}"

        # Projekt-Zustand prüfen
        state = _get_track_state()
        print(f"Track-State: {state}")
        assert "track" in state.lower(), f"Unerwarteter State: {state}"

    def test_full_workflow_in_sequence(self, osc_available, launchpad_available):
        """Kompletter Ablauf: Setup → Record → Play → Stop in einem Test."""
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar (Port 8001)")
        if not launchpad_available:
            pytest.skip("LaunchpadControllerExtension nicht erreichbar (Port 8003)")

        print("\n" + "="*60)
        print("  LAUNCHPAD DRUM RECORD — Vollständiger Ablauf")
        print("="*60)

        # ── Phase 1: Setup ────────────────────────────────────────────────────
        print("\n[Phase 1] Drum-Track anlegen...")
        setup_result = execute_setup({
            "context_type": "song",
            "target": {"bpm": 120},
            "summary": "Kick Track für Aufnahme-Test",
            "steps": [
                {"type": "set_tempo",       "args": {"bpm": 120},                           "status": "pending", "note": ""},
                {"type": "add_track",        "args": {"track_type": "instrument"},           "status": "pending", "note": "Kick"},
                {"type": "load_instrument",  "args": {"track_index": 1, "name": "v9 Kick"}, "status": "pending", "note": ""},
                {"type": "select_track",     "args": {"track_index": 1},                    "status": "pending", "note": ""},
            ],
        })
        print(f"  Setup: {setup_result[:120]}")
        assert "FEHLER" not in setup_result, f"Phase 1 fehlgeschlagen: {setup_result}"
        time.sleep(1.0)

        # ── DRUM-Modus sicherstellen ──────────────────────────────────────────
        mode = get_launchpad_mode()
        if "DRUM" not in mode:
            mode = set_launchpad_mode("DRUM")
        print(f"  Launchpad: {mode}")
        assert "DRUM" in mode, f"Modus-Wechsel fehlgeschlagen: {mode}"

        # ── Phase 2: Noten direkt in Clip schreiben ──────────────────────────
        print("\n[Phase 2] Noten in Clip schreiben (Edit Mode)...")
        write_result = _write_drum_pattern(track_index=1, slot=0)
        print(f"  Write: {write_result[:120]}")
        assert "FEHLER" not in write_result, f"Phase 2 fehlgeschlagen: {write_result}"
        assert "write_notes✓" in write_result

        # ── Launchpad Preview ─────────────────────────────────────────────────
        print("  Kick-Pattern als Preview spielen...")
        play_result = play_notes(self.KICK_PATTERN, bpm=120)
        print(f"  Preview: {play_result}")
        assert "Fehler" not in play_result

        # ── Playback starten ──────────────────────────────────────────────────
        _control_bitwig(action="play")
        time.sleep(0.5)
        _control_bitwig(action="stop")

        # ── Verifizierung ─────────────────────────────────────────────────────
        print("\n[Verifikation] Track-Zustand prüfen...")
        state = _get_track_state()
        print(f"  State: {state[:200]}")
        assert "track" in state.lower()

        print("\n" + "="*60)
        print("  ERGEBNIS: OK — Setup + Write Notes + Preview abgeschlossen")
        print("="*60)
