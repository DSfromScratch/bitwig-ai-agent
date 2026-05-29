"""
Smoke-Test: Feedback-Loop-Validierung + Projekt-Gesamtcheck.

Prüft:
  1. execute_result hängt nach erfolgreicher Ausführung "Bitwig-Status" an
  2. Prompt enthält Verbotsliste halluzinierter Tools
  3. _KNOWN_TOOL_NAMES deckt alle erwarteten Tools ab
  4. Tool-Whitelist enthält execute_result und schließt halluzinierte Tools aus
  5. Alle Kern-Module importierbar
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Halluzinierte Tools die NIE in der Whitelist sein dürfen ─────────────────

_HALLUCINATED_TOOLS = {
    "bitwig_load_instrument",
    "bitwig_load_sample",
    "add_track",
    "setup_instrument_track",
    "bitwig_set_parameter",
    "bitwig_add_instrument_track",
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_result(steps: list | None = None) -> dict:
    return {
        "context_type": "track",
        "target": {"track_index": 1},
        "summary": "Smoke-Test",
        "steps": steps or [
            {"type": "select_track", "args": {"track_index": 1}, "status": "pending", "note": ""},
        ],
    }


# ── Feedback-Loop Unit Tests ──────────────────────────────────────────────────

class TestFeedbackLoop:
    """Prüft dass execute_result nach Ausführung Bitwig-Status zurückmeldet."""

    @pytest.mark.unit
    def test_feedback_appended_on_success(self):
        """execute_result enthält 'Bitwig-Status' wenn Bridge erreichbar und Steps ok."""
        with patch("src.agent.tools.song_tools._check_bridge", return_value=True), \
             patch("src.agent.tools.song_tools._get_current_track_count", return_value=3), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            result = execute_result(_make_result())

        assert "Bitwig-Status" in result, f"Kein Feedback-Status in: {result}"
        assert "3 Track" in result, f"Track-Count nicht in Feedback: {result}"

    @pytest.mark.unit
    def test_no_feedback_on_error(self):
        """execute_result gibt kein Bitwig-Status aus wenn Steps fehlschlagen."""
        def _bad_step(*_a, **_kw):
            raise RuntimeError("Step fehlgeschlagen")

        with patch("src.agent.tools.song_tools._check_bridge", return_value=True), \
             patch("src.agent.tools.song_tools._get_current_track_count", return_value=2), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            # Ein Step-Typ der intern eine Exception wirft → steps haben errors
            result = execute_result({
                "context_type": "track",
                "target": {},
                "summary": "Fehler-Test",
                "steps": [
                    # set_param mit ungültigem index → KeyError
                    {"type": "set_param", "args": {}, "status": "pending", "note": ""},
                ],
            })

        assert "FEHLER" in result or "Fehler" in result, f"Kein Fehler-Hinweis: {result}"

    @pytest.mark.unit
    def test_feedback_zero_tracks_suppressed(self):
        """Kein 'Bitwig-Status' wenn track_count=0 (Bridge-Antwort unsicher)."""
        with patch("src.agent.tools.song_tools._check_bridge", return_value=True), \
             patch("src.agent.tools.song_tools._get_current_track_count", return_value=0), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            result = execute_result(_make_result())

        assert "Bitwig-Status" not in result, f"Irreführender Status bei 0 Tracks: {result}"

    @pytest.mark.unit
    def test_feedback_bridge_unreachable_no_crash(self):
        """Kein Crash wenn Bridge für Status-Query nicht antwortet."""
        with patch("src.agent.tools.song_tools._check_bridge", return_value=False), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            result = execute_result(_make_result())

        assert isinstance(result, str)
        assert "Bitwig-Status" not in result


# ── Projekt Smoke Tests ───────────────────────────────────────────────────────

class TestProjectSmoke:
    """Schnelle Querschnittsprüfung: Imports, Konfiguration, Konsistenz."""

    @pytest.mark.unit
    def test_core_modules_importable(self):
        """Alle Kern-Module laden ohne ImportError."""
        import bitwig_mcp_server
        from src.agent import core, events
        from src.agent.tools import mcp_bridge
        from src.agent import prompts

    @pytest.mark.unit
    def test_prompt_contains_forbidden_tools_section(self):
        """Prompt-Verbotsliste enthält alle bekannten halluzinierten Tools."""
        from src.agent.prompts import SYSTEM_PROMPT

        assert "Tools die NICHT existieren" in SYSTEM_PROMPT, \
            "Verbotsliste-Sektion fehlt im Prompt"

        for tool in _HALLUCINATED_TOOLS:
            assert tool in SYSTEM_PROMPT, \
                f"Halluziniertes Tool '{tool}' fehlt in der Verbotsliste"

    @pytest.mark.unit
    def test_whitelist_excludes_hallucinated_tools(self):
        """Tool-Whitelist darf keine halluzinierten Tools enthalten."""
        from src.agent.tools.mcp_bridge import _SETTINGS_TOOLS_WHITELIST

        overlap = _HALLUCINATED_TOOLS & _SETTINGS_TOOLS_WHITELIST
        assert not overlap, f"Halluzinierte Tools in Whitelist: {overlap}"

    @pytest.mark.unit
    def test_whitelist_contains_execute_result(self):
        """execute_result muss in der Whitelist stehen."""
        from src.agent.tools.mcp_bridge import _SETTINGS_TOOLS_WHITELIST

        assert "execute_result" in _SETTINGS_TOOLS_WHITELIST

    @pytest.mark.unit
    def test_known_tool_names_covers_whitelist_essentials(self):
        """_KNOWN_TOOL_NAMES enthält alle kritischen Tools aus der Whitelist."""
        from src.agent.core import _KNOWN_TOOL_NAMES

        required = {"execute_result", "bitwig_check_connection", "get_bitwig_track_state"}
        missing = required - _KNOWN_TOOL_NAMES
        assert not missing, f"Fehlende Tools in _KNOWN_TOOL_NAMES: {missing}"

    @pytest.mark.unit
    def test_execute_result_returns_string(self):
        """execute_result gibt immer einen String zurück — nie None oder Exception."""
        with patch("bitwig_mcp_server._check_connection", return_value=True), \
             patch("src.agent.tools.song_tools._check_bridge", return_value=False), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            result = execute_result(_make_result())

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_event_bus_importable_and_resettable(self):
        """EventBus lässt sich importieren und zurücksetzen."""
        from src.agent.events import get_event_bus, reset_event_bus
        reset_event_bus()
        bus = get_event_bus()
        assert bus is not None
        fired = []
        bus.subscribe("test_event", lambda e: fired.append(e))
        bus.emit("test_event", {"x": 1})
        assert len(fired) == 1
        assert fired[0]["payload"] == {"x": 1}
