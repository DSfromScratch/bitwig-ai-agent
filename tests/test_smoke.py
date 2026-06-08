"""
Smoke-Test: Feedback-Loop-Validierung + Projekt-Gesamtcheck.

Prüft:
  1. execute_result hängt nach erfolgreicher Ausführung "Bitwig-Status" an
  2. Prompt enthält Verbotsliste halluzinierter Tools
  3. Registry deckt alle kritischen Tools ab
  4. Tool-Whitelist schließt halluzinierte Tools aus
  5. Alle Kern-Module importierbar + MCP-Server-Struktur
  6. Tool-Call-Parser (QwenXML, Truncated, Composite)
  7. UUID-Lookup: exakter Match, Aliase, Reverse-Subset, kein Match
  8. Scoring: Drums/Bass/Gitarre werden korrekt bewertet
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))  # peer test imports (test_e2e_guitar)

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
        with patch("src.agent.osc.track_state._check_bridge", return_value=True), \
             patch("src.agent.osc.track_state._get_current_track_count", return_value=3), \
             patch("bitwigbridge.executor._exec_step_and_wait", return_value="select_track"), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            result = execute_result(_make_result())

        assert "Bitwig-Status" in result, f"Kein Feedback-Status in: {result}"
        assert "3 Track" in result, f"Track-Count nicht in Feedback: {result}"

    @pytest.mark.unit
    def test_no_feedback_on_error(self):
        """execute_result gibt Fehler-Hinweis wenn Steps fehlschlagen."""
        with patch("src.agent.osc.track_state._check_bridge", return_value=True), \
             patch("bitwigbridge.executor._exec_step_and_wait", return_value="error:timeout"), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            result = execute_result({
                "context_type": "track",
                "target": {},
                "summary": "Fehler-Test",
                "steps": [
                    {"type": "set_param", "args": {}, "status": "pending", "note": ""},
                ],
            })

        assert ("FEHLER" in result or "Fehler" in result or "✗" in result
                or "error" in result.lower()), f"Kein Fehler-Hinweis: {result}"

    @pytest.mark.unit
    def test_feedback_zero_tracks_suppressed(self):
        """Kein 'Bitwig-Status' wenn track_count=0 (Bridge-Antwort unsicher)."""
        with patch("src.agent.osc.track_state._check_bridge", return_value=True), \
             patch("src.agent.osc.track_state._get_current_track_count", return_value=0), \
             patch("bitwigbridge.executor._exec_step_and_wait", return_value="select_track"), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            result = execute_result(_make_result())

        assert "Bitwig-Status" not in result, f"Irreführender Status bei 0 Tracks: {result}"

    @pytest.mark.unit
    def test_feedback_bridge_unreachable_no_crash(self):
        """Kein Crash wenn Bridge für Status-Query nicht antwortet."""
        with patch("src.agent.osc.track_state._check_bridge", return_value=False), \
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
        from src.agent import core, events, prompts
        from src.agent.tools import mcp_bridge
        from src.bitwig_executor import execute_setup, execute_result

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
    def test_whitelist_contains_execute_setup(self):
        """execute_setup muss in der Whitelist stehen (Launchpad-Workflow)."""
        from src.agent.tools.mcp_bridge import _SETTINGS_TOOLS_WHITELIST

        assert "execute_setup" in _SETTINGS_TOOLS_WHITELIST
        assert "execute_result" not in _SETTINGS_TOOLS_WHITELIST
        assert "compose_notes" not in _SETTINGS_TOOLS_WHITELIST

    @pytest.mark.unit
    def test_known_tool_names_covers_whitelist_essentials(self):
        """Alle kritischen Tools sind in der Registry (Launchpad-Workflow)."""
        from src.agent.recovery import _get_known_tool_names

        required = {"execute_setup", "check_bitwig_connection", "get_bitwig_track_state"}
        missing = required - _get_known_tool_names()
        assert not missing, f"Fehlende Tools in der Registry: {missing}"

    @pytest.mark.unit
    def test_execute_result_returns_string(self):
        """execute_result gibt immer einen String zurück — nie None oder Exception."""
        with patch("bitwig_mcp_server._check_connection", return_value=True), \
             patch("src.agent.tools.bitwig.song_tools._check_bridge", return_value=False), \
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

    @pytest.mark.unit
    def test_mcp_server_importable(self):
        """bitwig_mcp_server importierbar und FastMCP-Instanz vorhanden."""
        import bitwig_mcp_server as srv
        assert hasattr(srv, "mcp")

    @pytest.mark.unit
    def test_mcp_server_osc_constants(self):
        """OSC-Konstanten im MCP-Server korrekt gesetzt (Host kann via BITWIG_HOST überschrieben werden)."""
        import bitwig_mcp_server as srv
        assert srv.OSC_HOST in ("127.0.0.1", "localhost") or len(srv.OSC_HOST) > 0
        assert srv.OSC_PORT == 8001

    @pytest.mark.unit
    def test_mcp_server_note_counts_dict(self):
        """_note_counts Dict im MCP-Server vorhanden."""
        import bitwig_mcp_server as srv
        assert hasattr(srv, "_note_counts")
        assert isinstance(srv._note_counts, dict)


# ── Tool-Call-Parser Tests ────────────────────────────────────────────────────

class TestToolCallParsers:
    """Parser-Kette: QwenXML, Truncated (Brace/Array-Truncation), Composite."""

    @pytest.mark.unit
    def test_qwen_xml_parser_complete(self):
        """QwenXMLParser erkennt vollständiges <tool_call>{...}</tool_call>."""
        from langchain_core.messages import AIMessage
        from src.agent.parsing.tool_call_parsers import QwenXMLParser

        content = '<tool_call>{"name":"execute_result","arguments":{"plan":{"steps":[]}}}</tool_call>'
        result = QwenXMLParser().parse(AIMessage(content=content))
        assert result is not None and len(result) == 1
        assert result[0]["name"] == "execute_result"
        assert result[0]["args"] == {"plan": {"steps": []}}

    @pytest.mark.unit
    def test_truncated_xml_unclosed_brace(self):
        """TruncatedXMLParser repariert fehlendes } am Ende des JSON."""
        from langchain_core.messages import AIMessage
        from src.agent.parsing.tool_call_parsers import TruncatedXMLParser

        content = '<tool_call>{"name":"execute_result","arguments":{"track_index":1}'
        result = TruncatedXMLParser().parse(AIMessage(content=content))
        assert result is not None, "TruncatedXMLParser gab None zurück für unclosed-brace"
        assert result[0]["name"] == "execute_result"

    @pytest.mark.unit
    def test_truncated_xml_unclosed_array(self):
        """TruncatedXMLParser repariert fehlendes ] in verschachteltem Array."""
        from langchain_core.messages import AIMessage
        from src.agent.parsing.tool_call_parsers import TruncatedXMLParser

        content = '<tool_call>{"name":"write_notes","arguments":{"notes":[{"pitch":60,"step":0}'
        result = TruncatedXMLParser().parse(AIMessage(content=content))
        assert result is not None, "TruncatedXMLParser gab None zurück für unclosed-array"
        assert result[0]["name"] == "write_notes"
        assert isinstance(result[0]["args"].get("notes"), list)

    @pytest.mark.unit
    def test_composite_parser_falls_through_to_qwen(self):
        """CompositeParser fällt von OpenAI-Format auf QwenXML durch."""
        from langchain_core.messages import AIMessage
        from src.agent.parsing.tool_call_parsers import TOOL_CALL_PARSER

        content = '<tool_call>{"name":"get_bitwig_track_state","arguments":{}}</tool_call>'
        result = TOOL_CALL_PARSER.extract(AIMessage(content=content))
        assert len(result) == 1
        assert result[0]["name"] == "get_bitwig_track_state"

    @pytest.mark.unit
    def test_patch_message_sets_tool_calls_and_strips_xml(self):
        """patch_message füllt tool_calls und entfernt <tool_call>-Tags aus Content."""
        from langchain_core.messages import AIMessage
        from src.agent.parsing.tool_call_parsers import TOOL_CALL_PARSER

        content = 'Denke nach... <tool_call>{"name":"execute_result","arguments":{"x":1}}</tool_call>'
        patched = TOOL_CALL_PARSER.patch_message(AIMessage(content=content))
        assert patched.tool_calls, "tool_calls leer nach patch_message"
        assert patched.tool_calls[0]["name"] == "execute_result"
        assert "<tool_call>" not in (patched.content or ""), "XML-Tag nicht entfernt"


# ── UUID-Lookup Tests ─────────────────────────────────────────────────────────

# Minimal-Map: deckt alle Lookup-Pfade ab ohne Neo4j/Extension-Abhängigkeit
_TEST_UUID_MAP = {
    "phase-4":        "uuid-phase4",
    "fm-4":           "uuid-fm4",
    "v9 kick":        "uuid-kick",
    "v9 snare":       "uuid-snare",
    "v9 hi-hat":      "uuid-hihat-closed",
    "v9 open hi-hat": "uuid-hihat-open",
    "hi-hat":         "uuid-hihat-closed",  # plain alias (wie in Java BUILTIN_UUIDS)
}


class TestUUIDLookup:
    """_lookup_device_uuid: exakter Match, Aliase, Reverse-Subset, kein Treffer."""

    def _lookup(self, name: str) -> str | None:
        with patch("src.agent.osc.device_uuid._DEVICE_UUID_CACHE", _TEST_UUID_MAP):
            from src.agent.tools.bitwig.song_tools import _lookup_device_uuid
            return _lookup_device_uuid(name)

    @pytest.mark.unit
    def test_exact_match(self):
        """Exakter Name → sofortiger Cache-Hit."""
        assert self._lookup("phase-4") == "uuid-phase4"

    @pytest.mark.unit
    def test_plain_alias_match(self):
        """Kurzform 'hi-hat' (plain alias) → exakter Cache-Hit."""
        assert self._lookup("hi-hat") == "uuid-hihat-closed"

    @pytest.mark.unit
    def test_word_subset_match(self):
        """'v9 Closed Hi-Hat' → 'v9 hi-hat' via Wort-Teilmenge (closed ignoriert)."""
        result = self._lookup("v9 Closed Hi-Hat")
        assert result == "uuid-hihat-closed", f"Wort-Subset fehlgeschlagen: {result}"

    @pytest.mark.unit
    def test_reverse_subset_match(self):
        """'Hat' ohne Alias in Map → 'v9 hi-hat' via Reverse-Subset-Matching."""
        # _TEST_UUID_MAP hat kein "hat" allein, aber "v9 hi-hat" ⊇ {"hat"}
        result = self._lookup("Hat")
        assert result == "uuid-hihat-closed", f"Reverse-Subset fehlgeschlagen: {result}"

    @pytest.mark.unit
    def test_no_match_returns_none(self):
        """Unbekannter Name → None (kein Crash, kein False-Positive)."""
        result = self._lookup("Imaginary Synth 9000 XYZ")
        assert result is None, f"Kein-Treffer lieferte unerwartet: {result}"


# ── Scoring Tests ─────────────────────────────────────────────────────────────

def _bd_score(entry: str) -> float:
    """Extrahiert Float-Score aus Breakdown-String '… → 0.25'.
    Wirft AssertionError (nicht ValueError) wenn Format unerwartet ist.
    """
    try:
        return float(entry.split("→")[-1].strip())
    except ValueError:
        raise AssertionError(f"Kann Score nicht aus Breakdown parsen: {entry!r}")


class TestScoring:
    """score_guitar_state: Drums/Bass/Gitarre werden korrekt bewertet.

    Launchpad-Workflow: Drums/Bass nach Track-Existenz (track_names), nicht Noten.
    Gewichtung: Drums=0.30, Bass=0.30, Guitar=0.30, Tempo=0.10.
    """

    @pytest.mark.unit
    def test_drums_full_score(self):
        """3 Drum-Tracks in Bitwig → vollen Drum-Score (0.30)."""
        from test_e2e_guitar import score_guitar_state
        track_names = ["v9 kick", "v9 snare", "v9 hat closed"]
        _, bd = score_guitar_state(3, {}, track_names=track_names)
        assert _bd_score(bd["drums"]) == pytest.approx(0.30), f"Drums: {bd['drums']}"

    @pytest.mark.unit
    def test_bass_fm4_score(self):
        """FM-4 Track in Bitwig → vollen Bass-Score (0.30)."""
        from test_e2e_guitar import score_guitar_state
        _, bd = score_guitar_state(1, {}, track_names=["fm-4 bass"])
        assert _bd_score(bd["bass"]) == pytest.approx(0.30), f"Bass: {bd['bass']}"

    @pytest.mark.unit
    def test_phase4_not_counted_as_bass(self):
        """Phase-4 wird als Gitarre (nicht Bass) gewertet — kritischer Fehler wenn falsch."""
        from test_e2e_guitar import score_guitar_state
        note_counts = {"phase-4": 4}
        _, bd = score_guitar_state(1, note_counts, track_names=["phase-4"])
        assert _bd_score(bd["bass"])   == pytest.approx(0.0), f"Phase-4 fälschlicherweise als Bass: {bd['bass']}"
        assert _bd_score(bd["guitar"]) >  0.0,                f"Phase-4 nicht als Gitarre erkannt: {bd['guitar']}"

    @pytest.mark.unit
    def test_full_arrangement_component_scores(self):
        """Drums + Bass + Gitarre + Tempo → jede Komponente korrekt bewertet."""
        from test_e2e_guitar import score_guitar_state
        track_names = ["v9 kick", "v9 snare", "v9 hat closed", "fm-4 bass", "phase-4"]
        note_counts = {"phase-4": 4}   # nur Gitarren-Noten (OOP-Pfad)
        score, bd = score_guitar_state(5, note_counts, result_text="Tempo: 120 BPM",
                                        track_names=track_names)
        assert _bd_score(bd["drums"])  == pytest.approx(0.30), f"Drums: {bd['drums']}"
        assert _bd_score(bd["bass"])   == pytest.approx(0.30), f"Bass:  {bd['bass']}"
        assert _bd_score(bd["guitar"]) == pytest.approx(0.30), f"Guitar:{bd['guitar']}"
        assert score == pytest.approx(1.00), f"Gesamt-Score falsch: {score}\n{bd}"
