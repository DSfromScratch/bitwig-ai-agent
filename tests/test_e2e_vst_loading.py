"""
VST Loading Smoke Test — Mac + BitwigStepPlugin.

Prüft:
  Unit:        Pattern-Tools für alle VST-Instrument-Typen
  Integration: Alle installierten VSTs laden via Browser-Navigation
               (Art → Plug-ins → selectFirstFile/selectNextFile → commit)

Installierte VSTs auf Mac:
  Dexed, OB-Xd Legacy, Surge XT, VB-MELLOW, VB-ROYAL, VD-HEAVY, VG-IRON2, VG-SILK2

Vorbedingungen (Integration):
  - Bitwig läuft auf Mac (192.168.0.4), BitwigStepPlugin aktiv (Port 8002)
  - Agent Host (IP) = 192.168.0.3 in BitwigStepPlugin-Einstellungen
  - Firewall: UDP 9002 offen auf Linux

Ausführen:
    pytest tests/test_e2e_vst_loading.py -m unit -v
    pytest tests/test_e2e_vst_loading.py -m integration -v -s
"""
import time
import pytest

from src.bitwig_executor import execute_setup
from src.agent.tools.pattern_tools import (
    write_pattern, _drums, _bass, _chords, _melody, _root_midi,
    _808_kick, _808_snare,
)


# ── Konstanten ────────────────────────────────────────────────────────────────

# Alle auf Mac installierten VSTs (Name wie im Bitwig-Browser)
MAC_VSTS = [
    "Surge XT",
    "Dexed",
    "OB-Xd Legacy",
    "VB-MELLOW",
    "VB-ROYAL",
    "VG-IRON2",
    "VG-SILK2",
    "VD-HEAVY",
]

# write_pattern Instrument-Mapping für VSTs
VST_PATTERN_MAP = {
    "Surge XT":    ("bass",   "rock",    "A"),
    "Dexed":       ("chords", "jazz",    "C"),
    "OB-Xd Legacy":("chords", "pop",     "C"),
    "VB-MELLOW":   ("bass",   "jazz",    "A"),
    "VB-ROYAL":    ("bass",   "rock",    "A"),
    "VG-IRON2":    ("chords", "rock",    "A"),
    "VG-SILK2":    ("chords", "pop",     "C"),
    "VD-HEAVY":    ("drums",  "rock",    "C"),
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def osc_available():
    """True wenn BitwigStepPlugin auf Mac (Port 8002) antwortet."""
    import socket
    from pythonosc import udp_client
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(3.0)
    try:
        sock.bind(("", 9002))
    except OSError:
        pass
    try:
        udp_client.SimpleUDPClient("192.168.0.4", 8002).send_message("/ping", 1)
        sock.recvfrom(128)
        return True
    except socket.timeout:
        return False
    finally:
        sock.close()


# ── Unit Tests ────────────────────────────────────────────────────────────────

class TestPatternToolsVST:
    """Pattern-Generierung für alle VST-Instrument-Typen (kein Bitwig nötig)."""

    @pytest.mark.unit
    def test_surge_xt_bass_pattern(self):
        notes = _bass("rock", 2, _root_midi("A", 2), "basic")
        assert len(notes) > 0
        assert all(n["pitch"] >= 28 for n in notes), "Bass-Noten zu hoch"

    @pytest.mark.unit
    def test_dexed_chord_pattern(self):
        notes = _chords("jazz", 2, ["Dm7", "G7", "Cmaj7", "Am7"], "basic")
        assert len(notes) > 0

    @pytest.mark.unit
    def test_obxd_chord_pattern(self):
        notes = _chords("pop", 2, ["C", "G", "Am", "F"], "arpeggio")
        assert len(notes) > 0

    @pytest.mark.unit
    def test_vb_mellow_bass_jazz(self):
        notes = _bass("jazz", 2, _root_midi("A", 2), "basic")
        assert len(notes) > 0

    @pytest.mark.unit
    def test_vb_royal_bass_rock(self):
        notes = _bass("rock", 2, _root_midi("A", 2), "full")
        assert len(notes) > 0

    @pytest.mark.unit
    def test_vg_iron2_chord_rock(self):
        notes = _chords("rock", 2, ["Am", "F", "C", "G"], "staccato")
        assert len(notes) > 0

    @pytest.mark.unit
    def test_vg_silk2_chord_pop(self):
        notes = _chords("pop", 2, ["C", "G", "Am", "F"], "sustained")
        assert len(notes) > 0

    @pytest.mark.unit
    def test_vd_heavy_drum_pattern(self):
        notes = _drums("rock", 2, "full")
        pitches = {n["pitch"] for n in notes}
        assert 36 in pitches, "Kein Kick (36)"
        assert 38 in pitches, "Keine Snare (38)"
        assert 42 in pitches, "Kein HiHat (42)"

    @pytest.mark.unit
    @pytest.mark.parametrize("instrument,ptype,genre,key", [
        (vst, *VST_PATTERN_MAP[vst]) for vst in MAC_VSTS
    ])
    def test_write_pattern_dispatch(self, instrument, ptype, genre, key):
        """write_pattern erkennt jeden VST-Typ korrekt ohne Bitwig."""
        from unittest.mock import patch
        with patch("src.bitwig_executor.compose_notes", return_value="[compose_notes] ✓"):
            result = write_pattern.invoke({
                "track_index": 1,
                "instrument": instrument,
                "genre": genre,
                "bpm": 120,
                "bars": 2,
                "key": key,
            })
        assert "Fehler" not in result.lower(), f"write_pattern Fehler für {instrument}: {result}"


# ── Integration Tests ─────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.slow
class TestVSTLoadingMac:
    """Alle VSTs auf Mac laden — Art → Plug-ins → Instrument."""

    def _clear(self):
        """Alle Tracks löschen (vor + nach Test)."""
        execute_setup({
            "context_type": "song", "target": {},
            "summary": "Tracks löschen",
            "steps": [{"type": "clear_tracks", "args": {}, "status": "pending", "note": ""}],
        })
        time.sleep(1)

    def test_load_all_vsts(self, osc_available):
        """Alle VSTs sequenziell laden — sauberer Zustand vor + nach Test."""
        if not osc_available:
            pytest.skip("BitwigStepPlugin nicht erreichbar (Port 8002 auf Mac)")

        from src.agent.osc.circuit_breaker import get_circuit

        self._clear()
        results = {}

        try:
            for track_idx, vst in enumerate(MAC_VSTS, start=1):
                get_circuit().reset()
                result = execute_setup({
                    "context_type": "song", "target": {},
                    "summary": f"VST Load Test: {vst}",
                    "steps": [
                        {"type": "add_track",       "args": {"track_type": "instrument"}, "status": "pending", "note": ""},
                        {"type": "load_instrument", "args": {"track_index": track_idx, "name": vst}, "status": "pending", "note": ""},
                    ],
                })
                ok = "load_instrument✓" in result
                results[vst] = ok
                err = next((l.strip() for l in result.split("\n") if "✗" in l), "")
                print(f"\n  {'✓' if ok else '✗'} [{track_idx}] {vst}" + (f"  → {err}" if err else ""))
                time.sleep(2)
        finally:
            self._clear()

        failed = [vst for vst, ok in results.items() if not ok]
        assert not failed, f"Folgende VSTs nicht geladen: {failed}"

    def test_all_vsts_and_write_pattern(self, osc_available):
        """Vollständiger Workflow: VST laden + Pattern schreiben für jeden Typ."""
        if not osc_available:
            pytest.skip("BitwigStepPlugin nicht erreichbar (Port 8002 auf Mac)")

        test_cases = [
            ("VD-HEAVY",  "drums",  "rock",  "C"),
            ("VB-ROYAL",  "bass",   "rock",  "A"),
            ("VG-SILK2",  "chords", "pop",   "C"),
            ("Surge XT",  "bass",   "dnb",   "A"),
        ]

        for i, (vst, ptype, genre, key) in enumerate(test_cases, start=1):
            # Setup
            setup = execute_setup({
                "context_type": "song", "target": {"bpm": 120},
                "summary": f"{vst} Full Test",
                "steps": [
                    {"type": "add_track",       "args": {"track_type": "instrument"}, "status": "pending", "note": ""},
                    {"type": "load_instrument", "args": {"track_index": i, "name": vst}, "status": "pending", "note": ""},
                ],
            })
            assert "load_instrument✓" in setup, f"Setup fehlgeschlagen: {setup}"

            # Pattern schreiben
            pattern_result = write_pattern.invoke({
                "track_index": i, "instrument": vst,
                "genre": genre, "bpm": 120, "bars": 2, "key": key,
            })
            assert "write_notes✓" in pattern_result, f"Pattern fehlgeschlagen: {pattern_result}"
            print(f"  ✓ {vst}: {pattern_result.split('|')[1].strip()}")
            time.sleep(0.5)
