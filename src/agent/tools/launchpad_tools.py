"""Launchpad MK2 Tools — direkte OSC-Anbindung, kein MCP-Overhead."""
import os
from dotenv import load_dotenv
load_dotenv()

_HOST = os.getenv("BITWIG_HOST", "127.0.0.1")
_PORT = int(os.getenv("BITWIG_PORT", "8001"))


def _osc(address: str, value=1) -> None:
    from pythonosc import udp_client
    udp_client.SimpleUDPClient(_HOST, _PORT).send_message(address, value)


def _require_bridge() -> str | None:
    try:
        from src.agent.tools.song_tools import _check_bridge
        if not _check_bridge(timeout=1.5):
            return "Fehler: BitwigAgentBridge nicht erreichbar (Port 8001)."
    except Exception:
        pass
    return None


def bitwig_launchpad_map(pad_note: int, action: str) -> str:
    """Weist einem Launchpad-Pad eine Bitwig-Aktion zu und setzt die LED-Farbe.

    Pad-Noten (Session-Modus): Untere Reihe 11–18, Reihe 2: 21–28, rechts: 19,29,...
    Aktionen: play_stop, stop, record, undo, loop_toggle, mute_toggle, next_track, prev_track

    Args:
        pad_note: MIDI-Note des Pads (z.B. 11 = unten links)
        action:   Aktion (play_stop | stop | record | undo | loop_toggle | mute_toggle | next_track | prev_track)
    """
    if err := _require_bridge(): return err
    _osc("/launchpad/map", [int(pad_note), str(action)])
    return f"Pad {pad_note} → {action} (LED aktiv)"


def bitwig_launchpad_led(pad_note: int, r: int, g: int, b: int) -> str:
    """Setzt die LED-Farbe eines Launchpad-Pads direkt.

    Args:
        pad_note: MIDI-Note des Pads
        r: Rot 0–63
        g: Grün 0–63
        b: Blau 0–63
    """
    if err := _require_bridge(): return err
    _osc("/launchpad/led", [int(pad_note), max(0, min(63, int(r))),
                             max(0, min(63, int(g))), max(0, min(63, int(b)))])
    return f"Pad {pad_note} LED = ({r},{g},{b})"


def bitwig_launchpad_clear() -> str:
    """Löscht alle Launchpad-Pad-Mappings und schaltet alle LEDs aus."""
    if err := _require_bridge(): return err
    _osc("/launchpad/clear", 1)
    return "Alle Launchpad-Mappings gelöscht, LEDs aus"
