"""
MCP-Bridge: Verbindet den LangGraph-Agent direkt mit dem bitwig_mcp_server.

Zwei Modi:
  A) Subprocess-Modus (sauber, stdio):    get_mcp_tools_subprocess()
  B) Direct-Modus (schnell, gleicher Prozess): get_mcp_tools_direct()

Der Direct-Modus ist empfohlen — kein Prozess-Overhead, alle 39 MCP-Tools sofort.
"""

from __future__ import annotations
import sys
import os
from pathlib import Path

# Projektpfad
PROJECT_ROOT = str(Path(__file__).parent.parent.parent.parent)


def get_mcp_tools_direct() -> list:
    """
    Extrahiert alle MCP-Tools aus bitwig_mcp_server.py als LangChain-Tools.

    Wandelt FastMCP-Tools in langchain_core.tools.StructuredTool um.
    Kein Subprocess, kein Overhead — direkt im selben Python-Prozess.

    Returns:
        Liste von LangChain-kompatiblen Tool-Objekten (call-fähig)
    """
    sys.path.insert(0, PROJECT_ROOT)

    # MCP-Server importieren (lädt alle @mcp.tool() Definitionen)
    import bitwig_mcp_server as srv
    from langchain_core.tools import StructuredTool
    import inspect

    lc_tools = []
    tool_manager = getattr(srv.mcp, "_tool_manager", None)
    if tool_manager is None:
        raise RuntimeError("FastMCP._tool_manager nicht gefunden — API geändert?")

    for name, mcp_tool in tool_manager._tools.items():
        fn = mcp_tool.fn
        sig = inspect.signature(fn)

        # Pydantic-Schema aus der FastMCP-Tool-Definition
        # FastMCP erstellt intern ein Schema — wir nutzen die Funktion direkt
        lc_tool = StructuredTool.from_function(
            func=fn,
            name=name,
            description=mcp_tool.description or fn.__doc__ or name,
            return_direct=False,
        )
        lc_tools.append(lc_tool)

    return lc_tools


async def get_mcp_tools_subprocess() -> list:
    """
    Verbindet zum MCP-Server als Subprocess via stdio.

    Saubere Trennung: Agent und MCP-Server laufen in separaten Prozessen.
    Erfordert laufenden MCP-Server ODER startet ihn als Subprocess.

    Returns:
        Liste von LangChain-MCP-Tools
    """
    from langchain_mcp_adapters.tools import load_mcp_tools
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server_path = os.path.join(PROJECT_ROOT, "bitwig_mcp_server.py")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_path],
        env={
            **os.environ,
            "NEO4J_URI": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            "NEO4J_USER": os.getenv("NEO4J_USER", "neo4j"),
            "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD", "neo4jllm"),
            "BITWIG_HOST": os.getenv("BITWIG_HOST", "127.0.0.1"),
            "BITWIG_PORT": os.getenv("BITWIG_PORT", "8001"),
        }
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            return tools


_SETTINGS_TOOLS_WHITELIST = {
    # Verbindung & Status
    "check_bitwig_connection",
    "bitwig_check_connection",
    "get_bitwig_track_state",
    # Transport
    "bitwig_play",
    "bitwig_stop",
    "bitwig_set_tempo",
    # Tracks
    "bitwig_add_instrument_track",
    "bitwig_add_audio_track",
    "bitwig_add_effect_track",
    "bitwig_add_group_track",
    "bitwig_select_track",
    "bitwig_set_track_volume",
    "bitwig_pan_track",
    "bitwig_solo_track",
    "bitwig_mute_track",
    "bitwig_set_send_level",
    # Devices laden & steuern
    "bitwig_load_instrument",
    "bitwig_browser_commit",
    "bitwig_browser_next",
    "bitwig_set_parameter",
    "bitwig_set_named_parameter",
    "bitwig_eq_band",
    # Allgemeine Bitwig-Kontrolle
    "control_bitwig",
    "setup_instrument_track",
    # Launchpad MK2
    "bitwig_launchpad_map",
    "bitwig_launchpad_led",
    "bitwig_launchpad_clear",
    # Wissensdatenbank
    "query_bitwig_docs",
}


def get_all_tools_combined() -> list:
    """Kombiniert MCP-Tools mit Agent-Tools — gefiltert auf Settings-Assistant-relevante Tools."""
    from src.agent.tools import ALL_TOOLS as agent_tools

    try:
        mcp_tools = get_mcp_tools_direct()
        mcp_names = {t.name for t in mcp_tools}

        # Nur Whitelist-Tools aus MCP
        filtered_mcp = [t for t in mcp_tools if t.name in _SETTINGS_TOOLS_WHITELIST]

        # Agent-Tools: nur Whitelist, ohne MCP-Duplikate
        unique_agent = [
            t for t in agent_tools
            if t.name in _SETTINGS_TOOLS_WHITELIST and t.name not in mcp_names
        ]

        return filtered_mcp + unique_agent
    except Exception as e:
        print(f"[mcp_bridge] MCP-Integration fehlgeschlagen: {e} — verwende Agent-Tools")
        return [t for t in agent_tools if t.name in _SETTINGS_TOOLS_WHITELIST]
