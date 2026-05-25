"""Unit Tests: MCP-Bridge (Agent ↔ MCP-Server Anbindung)."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestMcpBridgeDirect:
    """MCP-Tools direkt aus bitwig_mcp_server extrahieren."""

    @pytest.mark.unit
    def test_mcp_tools_loadable(self):
        from src.agent.tools.mcp_bridge import get_mcp_tools_direct
        tools = get_mcp_tools_direct()
        assert len(tools) > 0

    @pytest.mark.unit
    def test_expected_tools_present(self):
        from src.agent.tools.mcp_bridge import get_mcp_tools_direct
        tools = {t.name for t in get_mcp_tools_direct()}
        required = {
            "bitwig_play", "bitwig_stop", "bitwig_set_tempo",
            "bitwig_add_instrument_track", "bitwig_load_instrument",
            "bitwig_note_pattern", "bitwig_select_track",
            "bitwig_record_to_arrangement", "bitwig_arrange_view",
        }
        missing = required - tools
        assert not missing, f"Fehlende Tools: {missing}"

    @pytest.mark.unit
    def test_tool_count_reasonable(self):
        from src.agent.tools.mcp_bridge import get_mcp_tools_direct
        tools = get_mcp_tools_direct()
        assert 30 <= len(tools) <= 60, f"Unerwartete Tool-Anzahl: {len(tools)}"

    @pytest.mark.unit
    def test_tools_have_descriptions(self):
        from src.agent.tools.mcp_bridge import get_mcp_tools_direct
        tools = get_mcp_tools_direct()
        missing_desc = [t.name for t in tools if not t.description]
        assert len(missing_desc) == 0, f"Tools ohne Beschreibung: {missing_desc}"

    @pytest.mark.unit
    def test_combined_tools_include_agent_tools(self):
        from src.agent.tools.mcp_bridge import get_all_tools_combined
        from src.agent.tools import ALL_TOOLS
        combined = get_all_tools_combined()
        combined_names = {t.name for t in combined}
        # Agent-spezifische Tools die nicht im MCP sind
        agent_specific = {"verify_song", "get_bitwig_track_state", "query_bitwig_docs"}
        for name in agent_specific:
            assert name in combined_names, f"Agent-Tool fehlt: {name}"

    @pytest.mark.unit
    def test_no_duplicate_tool_names(self):
        from src.agent.tools.mcp_bridge import get_all_tools_combined
        tools = get_all_tools_combined()
        names = [t.name for t in tools]
        duplicates = [n for n in names if names.count(n) > 1]
        assert not duplicates, f"Doppelte Tool-Namen: {set(duplicates)}"

    @pytest.mark.unit
    def test_mcp_bridge_env_toggle(self):
        """AGENT_USE_MCP_BRIDGE=0 schaltet auf Standard-Tools zurück."""
        os.environ["AGENT_USE_MCP_BRIDGE"] = "0"
        try:
            # Muss importiert werden BEVOR das Modul cached ist
            import importlib
            import src.agent.core as core_mod
            importlib.reload(core_mod)
            tools = core_mod._get_tools()
            from src.agent.tools import ALL_TOOLS
            assert len(tools) == len(ALL_TOOLS)
        finally:
            os.environ["AGENT_USE_MCP_BRIDGE"] = "1"


class TestMcpServerStructure:
    """bitwig_mcp_server.py Struktur-Tests."""

    @pytest.mark.unit
    def test_mcp_server_importable(self):
        import bitwig_mcp_server as srv
        assert hasattr(srv, "mcp")

    @pytest.mark.unit
    def test_osc_constants_set(self):
        import bitwig_mcp_server as srv
        assert srv.OSC_HOST == "127.0.0.1"
        assert srv.OSC_PORT == 8001

    @pytest.mark.unit
    def test_note_counts_dict_exists(self):
        import bitwig_mcp_server as srv
        assert hasattr(srv, "_note_counts")
        assert isinstance(srv._note_counts, dict)
