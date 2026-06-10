"""
Bitwig Studio Integration — OSC via BitwigStepPluginExtension (Port 8002).

Alle Transport/Track/EQ-Befehle laufen über BitwigStepPluginExtension.
Kein separates DrivenByMoss / BitwigAgentBridgeExtension nötig.
"""

from __future__ import annotations

import time
from langchain_core.tools import tool


def _osc(host: str, port: int):
    from pythonosc import udp_client
    return udp_client.SimpleUDPClient(host, port)


def _send(client, address: str, value=1):
    client.send_message(address, value)


# ── DAWproject-Export ──────────────────────────────────────────────────────────

# ── Bitwig OSC Control (DrivenByMoss) ─────────────────────────────────────────

@tool
def control_bitwig(
    action: str,
    # Transport
    bpm: float = 0.0,
    # Track
    track_index: int = 1,
    track_type: str = "instrument",
    track_name: str = "",
    value: float = 0.5,
    # Device / Browser
    param_index: int = 1,
    browser_steps: int = 0,
    # EQ
    eq_band: int = 1,
    eq_freq: float = 0.0,
    eq_gain: float = 0.0,
    eq_q: float = 0.0,
    # Clip
    clip_index: int = 1,
    clip_beats: float = 4.0,
    # Netzwerk
    host: str = "",
    port: int = 0,
) -> dict:
    """Bitwig Transport/Track/Mix via OSC.
    action: play|stop|tempo(bpm)|record|loop|mute|solo|volume|pan|select_track|
            eq_freq|eq_gain|eq_q|launch_clip|create_clip

    Args:
        host:  OSC-Host (Standard: config.bitwig_host)
        port:  OSC-Port (Standard: config.bitwig_port = 8002)
    """
    try:
        from pythonosc import udp_client
    except ImportError:
        return {"error": "python-osc nicht installiert: uv pip install python-osc"}

    from src.agent.config import config
    _host = host or config.bitwig_host
    _port = port or config.bitwig_port
    _reply_port = config.bitwig_reply_port
    c = udp_client.SimpleUDPClient(_host, _port, allow_broadcast=False)
    # Festen Quellport setzen damit Bitwig's src.sendMessage() nicht auf Port 0 läuft
    try:
        c._sock.bind(("", _reply_port))
    except OSError:
        pass  # Port bereits belegt — ephemerer Port ist OK, Java-Seite hat jetzt try-catch
    sent = []

    def s(addr: str, val=1):
        c.send_message(addr, val)
        sent.append(f"{addr} {val}")

    def wait(ms: float = 100):
        time.sleep(ms / 1000)

    # ── Transport ──────────────────────────────────────────────────────────
    if action == "play":
        s("/transport/play", 1)
    elif action == "stop":
        s("/transport/stop", 0)
    elif action == "tempo" and bpm > 0:
        s("/tempo/raw", float(bpm))
    elif action == "record":
        s("/record", 1)
    elif action == "loop":
        s("/repeat", int(value))

    # ── Tracks ─────────────────────────────────────────────────────────────
    elif action == "add_track":
        addr = f"/track/add/{track_type}"
        s(addr, 1)
        wait(200)
        if track_name:
            # Neuer Track ist direkt selektiert → umbenennen via OSC nicht direkt
            # möglich, daher nur im Log vermerken
            sent.append(f"# Hinweis: Track bitte manuell in '{track_name}' umbenennen")
    elif action == "select_track":
        s(f"/track/{track_index}/select", 1)
    elif action == "remove_track":
        s(f"/track/{track_index}/remove", 1)
    elif action == "mute":
        s(f"/track/{track_index}/mute", int(value))
    elif action == "solo":
        s(f"/track/{track_index}/solo", int(value))
    elif action == "volume":
        s(f"/track/{track_index}/volume", float(value))
    elif action == "pan":
        s(f"/track/{track_index}/pan", float(value))

    # ── Browser / Devices ─────────────────────────────────────────────────
    elif action == "browser_device":
        s("/browser/device", 1)
        if browser_steps > 0:
            wait(300)
            for _ in range(browser_steps):
                s("/browser/result/+", 1)
                wait(80)
    elif action == "browser_preset":
        s("/browser/preset", 1)
        if browser_steps > 0:
            wait(300)
            for _ in range(browser_steps):
                s("/browser/result/+", 1)
                wait(80)
    elif action == "browser_next":
        for _ in range(max(1, browser_steps)):
            s("/browser/result/+", 1)
            wait(80)
    elif action == "browser_prev":
        for _ in range(max(1, browser_steps)):
            s("/browser/result/-", 1)
            wait(80)
    elif action == "browser_commit":
        s("/browser/commit", 1)
    elif action == "browser_cancel":
        s("/browser/cancel", 1)
    elif action == "set_param":
        s(f"/device/param/{param_index}/value", float(value))

    # ── EQ ─────────────────────────────────────────────────────────────────
    elif action == "eq_freq":
        # Hz → normalisierter Wert (20Hz=0, 20kHz=1, logarithmisch)
        import math
        normalized = math.log10(max(eq_freq, 20) / 20) / math.log10(20000 / 20)
        s(f"/eq/freq/{eq_band}", round(min(1.0, max(0.0, normalized)), 4))
    elif action == "eq_gain":
        # ±24 dB → 0-1 (0 dB = 0.5)
        normalized = (eq_gain + 24) / 48
        s(f"/eq/gain/{eq_band}", round(min(1.0, max(0.0, normalized)), 4))
    elif action == "eq_q":
        s(f"/eq/q/{eq_band}", round(min(1.0, max(0.0, eq_q)), 4))

    # ── Clips ───────────────────────────────────────────────────────────────
    elif action == "launch_clip":
        s(f"/track/{track_index}/clip/{clip_index}/launch", 1)
    elif action == "create_clip":
        s(f"/track/{track_index}/clip/{clip_index}/create", float(clip_beats))
    elif action == "record_clip":
        s(f"/track/{track_index}/clip/{clip_index}/record", 1)

    # ── Instrument nach Name laden ────────────────────────────────────────
    elif action == "load_instrument":
        # Öffnet Browser + navigiert automatisch zum Instrument via Katalog
        # track_name: welcher Track ausgewählt werden soll (Name als Hinweis)
        if track_index > 0:
            s(f"/track/{track_index}/select", 1)
            wait(200)
        s("/browser/device/load", track_name or "Phase-4")
        sent.append(f"# Lade Instrument: {track_name} auf Track {track_index}")

    # ── Effect ans Ende der Chain anhängen ───────────────────────────────
    elif action == "append_effect":
        # Fügt Effect NACH dem aktuellen Cursor-Device ein (End of Chain)
        # Verhindert versehentliches Einfügen vor Phase-4 o.ä.
        if track_index > 0:
            s(f"/track/{track_index}/select", 1)
            wait(200)
        s("/browser/device/append", track_name or "Reverb")
        wait(400)
        sent.append(f"# Füge Effect ans Ende der Chain an: {track_name} auf Track {track_index}")

    # ── Parameter nach Name setzen ────────────────────────────────────────
    elif action == "set_param_named":
        # track_name = Parameter-Name, value = Wert 0.0-1.0
        if track_index > 0:
            s(f"/track/{track_index}/select", 1)
            wait(100)
        c.send_message("/device/param/named", [track_name, float(value)])
        sent.append(f"# Param '{track_name}' = {value}")

    # ── Compound: Synth-Projekt einrichten ────────────────────────────────
    elif action == "setup_synth_project":
        track_defs = [
            ("Kick",   "instrument"),
            ("Snare",  "instrument"),
            ("HiHat",  "instrument"),
            ("Bass",   "instrument"),
            ("Melody", "instrument"),
            ("Pad",    "instrument"),
        ]
        sent.append("# Erstelle Instrument-Tracks für synthesiertes Projekt...")
        for tname, ttype in track_defs:
            s(f"/track/add/{ttype}", 1)
            wait(300)
            sent.append(f"# Track '{tname}' erstellt — bitte E-Kick/E-Snare/E-HiHat/FM-4/Phase-4/Polysynth zuweisen")
        sent.append("# Alle Tracks erstellt. Browser öffnet sich beim nächsten 'browser_device' Aufruf.")

    else:
        return {"error": (
            f"Unbekannte Aktion: '{action}'. "
            "Gültig: play, stop, tempo, record, loop, "
            "add_track, select_track, remove_track, mute, solo, volume, pan, "
            "browser_device, browser_preset, browser_next, browser_prev, "
            "browser_commit, browser_cancel, set_param, "
            "eq_freq, eq_gain, eq_q, "
            "launch_clip, create_clip, record_clip, "
            "load_instrument, append_effect, "
            "setup_synth_project"
        )}

    return {"status": "ok", "sent": sent, "host": _host, "port": _port}
