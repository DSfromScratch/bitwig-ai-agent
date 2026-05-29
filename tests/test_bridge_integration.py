"""
Bridge-Integration-Tests: Prüft execute_result → OSC → Bitwig end-to-end.

Erfordert laufende BitwigAgentBridge (wird übersprungen wenn nicht erreichbar).
Startet Bitwig Studio und aktiviert die Extension bevor diese Tests laufen.

Ausführen:
    pytest tests/test_bridge_integration.py -m bridge -v
"""
import pytest
import sys
import os
import socket
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

OSC_HOST = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_PORT = int(os.getenv("BITWIG_DM_PORT", "8001"))
REPLY_PORT = int(os.getenv("BITWIG_REPLY_PORT", "9001"))


# ── Fixtures ──────────────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "bridge: requires running BitwigAgentBridge")


def _bridge_reachable() -> bool:
    """Ping/Pong gegen die Bridge."""
    try:
        from pythonosc import udp_client
    except ImportError:
        return False

    received = threading.Event()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(2.0)
    try:
        sock.bind(("", REPLY_PORT))
    except OSError:
        pass

    def _listen():
        try:
            sock.recv(64)
            received.set()
        except Exception:
            pass

    threading.Thread(target=_listen, daemon=True).start()
    try:
        udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT).send_message("/ping", 1)
        return received.wait(2.0)
    except Exception:
        return False
    finally:
        sock.close()


@pytest.fixture(scope="session")
def bridge_available():
    return _bridge_reachable()


def _osc_send(address: str, value=1):
    from pythonosc import udp_client
    udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT).send_message(address, value)


def _call_execute_result(result: dict) -> str:
    """Ruft execute_result direkt auf (nicht via LLM)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    import importlib
    spec = importlib.util.spec_from_file_location(
        "bitwig_mcp_server",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "bitwig_mcp_server.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.execute_result(result)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBridgeConnection:

    @pytest.mark.bridge
    def test_ping_pong(self, bridge_available):
        """Bridge antwortet auf /ping mit /pong."""
        if not bridge_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")
        assert bridge_available, "Ping/Pong fehlgeschlagen"

    @pytest.mark.bridge
    def test_bridge_check_connection_tool(self, bridge_available):
        """check_bitwig_connection gibt connected=true zurück."""
        if not bridge_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")

        from bitwig_mcp_server import bitwig_check_connection
        result = bitwig_check_connection()
        assert "erreichbar" in result.lower() or "port" in result.lower(), (
            f"Unerwartete Antwort: {result}"
        )


class TestExecuteResultBridge:
    """execute_result end-to-end via echter Bridge."""

    @pytest.mark.bridge
    def test_set_tempo(self, bridge_available):
        """set_tempo Step setzt BPM ohne Fehler."""
        if not bridge_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")

        from bitwig_mcp_server import execute_result
        result = execute_result({
            "context_type": "song",
            "target": {"bpm": 90},
            "summary": "Tempo-Test",
            "steps": [
                {"type": "set_tempo", "args": {"bpm": 90}, "status": "pending", "note": ""},
            ]
        })
        assert "FEHLER" not in result, f"set_tempo fehlgeschlagen: {result}"
        assert "90" in result, f"BPM nicht in Antwort: {result}"

    @pytest.mark.bridge
    def test_select_track(self, bridge_available):
        """select_track Step selektiert Track ohne Fehler."""
        if not bridge_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")

        from bitwig_mcp_server import execute_result
        result = execute_result({
            "context_type": "track",
            "target": {"track_index": 1},
            "summary": "Track-Select-Test",
            "steps": [
                {"type": "select_track", "args": {"track_index": 1}, "status": "pending", "note": ""},
            ]
        })
        assert "FEHLER" not in result, f"select_track fehlgeschlagen: {result}"

    @pytest.mark.bridge
    @pytest.mark.slow
    def test_load_instrument_phase4(self, bridge_available):
        """load_instrument lädt Phase-4 auf Track 1 ohne Fehler."""
        if not bridge_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")

        from bitwig_mcp_server import execute_result
        result = execute_result({
            "context_type": "track",
            "target": {"track_index": 1},
            "summary": "Phase-4 laden",
            "steps": [
                {"type": "select_track", "args": {"track_index": 1}, "status": "pending", "note": ""},
                {"type": "load_instrument", "args": {"track_index": 1, "name": "Phase-4"}, "status": "pending", "note": ""},
            ]
        })
        assert "FEHLER" not in result, f"load_instrument fehlgeschlagen: {result}"
        assert "load_instrument" in result.lower() or "phase-4" in result.lower(), (
            f"Phase-4 nicht in Antwort: {result}"
        )

    @pytest.mark.bridge
    @pytest.mark.slow
    def test_full_track_setup(self, bridge_available):
        """Vollständiges Track-Setup: Instrument + Param + FX."""
        if not bridge_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")

        from bitwig_mcp_server import execute_result
        result = execute_result({
            "context_type": "track",
            "target": {"track_index": 1},
            "summary": "Smoke-Test: Phase-4 + Param + Reverb",
            "steps": [
                {"type": "select_track",    "args": {"track_index": 1},                     "status": "pending", "note": ""},
                {"type": "load_instrument", "args": {"track_index": 1, "name": "Phase-4"},  "status": "pending", "note": ""},
                {"type": "set_param",       "args": {"track_index": 1, "index": 3, "value": 0.35}, "status": "pending", "note": "Cutoff"},
                {"type": "append_effect",   "args": {"track_index": 1, "name": "Reverb"},   "status": "pending", "note": ""},
            ]
        })

        assert "FEHLER" not in result
        assert "4 Steps" in result or "4" in result, f"Nicht alle Steps ausgeführt: {result}"


class TestBridgeSmoke:
    """Schneller Smoke-Test — läuft in < 10s."""

    @pytest.mark.bridge
    def test_smoke_ping_tempo_select(self, bridge_available):
        """Ping + Tempo + Track-Select in einem Durchlauf."""
        if not bridge_available:
            pytest.skip("BitwigAgentBridge nicht erreichbar")

        assert bridge_available, "Ping fehlgeschlagen"

        from bitwig_mcp_server import execute_result
        result = execute_result({
            "context_type": "song",
            "target": {"bpm": 120},
            "summary": "Smoke-Test",
            "steps": [
                {"type": "set_tempo",    "args": {"bpm": 120},           "status": "pending", "note": ""},
                {"type": "select_track", "args": {"track_index": 1},     "status": "pending", "note": ""},
            ]
        })
        assert "FEHLER" not in result, f"Smoke-Test fehlgeschlagen: {result}"
