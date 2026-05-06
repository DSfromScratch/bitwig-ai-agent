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


def get_all_tools_combined() -> list:
    """
    Kombiniert MCP-Tools mit den Agent-eigenen Tools (song_tools).

    MCP-Tools (39):  bitwig_load_instrument, bitwig_note_pattern, bitwig_play, ...
    Agent-Tools (7): create_song_from_genre, verify_song, query_bitwig_docs, ...

    Duplikate werden durch MCP-Versionen ersetzt (vollständiger).
    """
    from src.agent.tools import ALL_TOOLS as agent_tools

    try:
        mcp_tools = get_mcp_tools_direct()
        mcp_names = {t.name for t in mcp_tools}

        # Agent-Tools die NICHT im MCP-Server sind (KB-Query, Song-Genre, etc.)
        unique_agent = [t for t in agent_tools if t.name not in mcp_names]

        combined = mcp_tools + unique_agent
        return combined
    except Exception as e:
        print(f"[mcp_bridge] MCP-Integration fehlgeschlagen: {e} — verwende Agent-Tools")
        return agent_tools
