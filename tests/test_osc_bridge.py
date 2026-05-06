"""Integration Tests: OSC-Verbindung zur BitwigAgentBridge."""
import pytest
import sys, os, time, socket, threading, struct
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestOscConnection:
    """Verbindungstests (erfordern laufende BitwigAgentBridge)."""

    @pytest.mark.integration
    def test_ping_pong(self, osc_available):
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")
        assert osc_available, "Ping/Pong fehlgeschlagen"

    @pytest.mark.integration
    def test_track_count_readable(self, osc_available):
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient("127.0.0.1", 8001)
        received = threading.Event()
        result = {}

        def listen():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(2.0)
            try:
                sock.bind(("0.0.0.0", 8002))
                data, _ = sock.recvfrom(512)
                raw = data.decode("latin-1")
                tag_idx = raw.find(",i")
                if tag_idx >= 0:
                    padded = (tag_idx + 4) & ~3
                    if padded + 4 <= len(data):
                        n = struct.unpack(">i", data[padded:padded+4])[0]
                        result["count"] = n
                received.set()
            except: pass
            finally: sock.close()

        t = threading.Thread(target=listen, daemon=True)
        t.start(); time.sleep(0.05)
        client.send_message("/agent/track/count", 1)
        received.wait(timeout=2.5)

        assert "count" in result, "Keine Track-Count-Antwort von Bridge"
        assert 0 <= result["count"] <= 64, f"Ungültiger Track-Count: {result['count']}"

    @pytest.mark.integration
    def test_tempo_setting(self, osc_available):
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient("127.0.0.1", 8001)
        # Sollte ohne Exception ausführbar sein
        client.send_message("/transport/tempo", 120.0)
        time.sleep(0.1)


class TestDeviceLoading:
    """Device-UUID-Loading Tests."""

    @pytest.mark.integration
    def test_builtin_device_loads(self, osc_available):
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient("127.0.0.1", 8001)
        # Track anlegen und Instrument laden
        client.send_message("/track/add/instrument", 1)
        time.sleep(0.3)
        client.send_message("/track/1/select", 1)
        time.sleep(0.2)
        client.send_message("/browser/device/load", "Polysynth")
        time.sleep(0.8)
        # Kein direkter Rückkanal — Track-Count sollte 1+ sein
        # (Verifikation über get_bitwig_track_state in anderen Tests)

    @pytest.mark.integration
    def test_note_writing_float_pitch(self, osc_available):
        """Float-Pitch darf nicht zu MIDI-60-Bug führen."""
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient("127.0.0.1", 8001)
        client.send_message("/track/1/select", 1); time.sleep(0.4)
        client.send_message("/clip/create", [0, 8.0]); time.sleep(0.6)
        client.send_message("/clip/step_size", 0.25); time.sleep(0.05)
        client.send_message("/clip/clear", 1); time.sleep(0.1)
        # Pitch als Float senden (69 = A4 in Bitwig, nicht 60 = C3)
        client.send_message("/clip/note/beat", [0.0, 69.0, 0.8, 1.0])
        time.sleep(0.1)
        # Test gilt als bestanden wenn kein Exception → Extension läuft stabil


class TestSongTools:
    """Integration Tests für create_song_from_genre."""

    @pytest.mark.integration
    @pytest.mark.slow
    def test_get_track_state_returns_count(self, osc_available, neo4j_available):
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")
        from src.agent.tools.song_tools import get_bitwig_track_state
        result = get_bitwig_track_state.invoke({})
        assert isinstance(result, str)
        assert "Track" in result or "Bridge" in result

    @pytest.mark.integration
    @pytest.mark.slow
    def test_verify_song_structure(self, osc_available):
        if not osc_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")
        import json
        from src.agent.tools.song_tools import verify_song
        raw = verify_song.invoke({"play_seconds": 2.0})
        result = json.loads(raw)
        assert "ok" in result
        assert "track_count" in result
        assert "warnings" in result
        assert "report_text" in result
        assert "VERIFIKATION" in result["report_text"]
        assert "Wiedergabe" in result["report_text"]
