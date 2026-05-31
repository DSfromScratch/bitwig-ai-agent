"""
MCP-Bridge: Tool-Whitelist für den Settings-Assistenten.

Die frühere get_mcp_tools_direct() / get_all_tools_combined() Logik wurde entfernt —
der Agent lädt Tools jetzt direkt aus src/agent/tools/__init__.py (ALL_TOOLS).
bitwig_mcp_server.py bleibt als optionaler MCP-Server nur für Claude Code.
"""

_SETTINGS_TOOLS_WHITELIST = {
    # Verbindung & Status
    "check_bitwig_connection",
    "bitwig_check_connection",
    "get_bitwig_track_state",
    # Transport
    "bitwig_play",
    "bitwig_stop",
    "bitwig_set_tempo",
    # Mixer
    "bitwig_select_track",
    "bitwig_set_track_volume",
    "bitwig_pan_track",
    "bitwig_solo_track",
    "bitwig_mute_track",
    "bitwig_eq_band",
    # Setup (Tracks, Instrumente, FX, Tempo)
    "execute_setup",
    # Allgemeine Bitwig-Kontrolle
    "control_bitwig",
    # Launchpad MK2
    "bitwig_launchpad_map",
    "bitwig_launchpad_led",
    "bitwig_launchpad_clear",
    # Wissensdatenbank
    "query_bitwig_docs",
}
