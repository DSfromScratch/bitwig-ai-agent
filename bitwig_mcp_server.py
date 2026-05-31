"""
Bitwig MCP Server — Claude Code kann Bitwig Studio direkt steuern.

Voraussetzung: BitwigAgentBridge.bwextension in Bitwig aktiv (Port 8001)

Starten:
    python bitwig_mcp_server.py

In Claude Code registrieren (~/.claude/settings.json):
    "mcpServers": {
        "bitwig": {
            "command": "/home/sija/bitwig-agent/.venv/bin/python",
            "args": ["/home/sija/bitwig-agent/bitwig_mcp_server.py"]
        }
    }
"""

import os
import time
from typing import Any
from mcp.server.fastmcp import FastMCP

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

mcp = FastMCP("Bitwig Studio")

load_dotenv()

OSC_HOST = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_PORT = int(os.getenv("BITWIG_DM_PORT", "8001"))

OSC_REPLY_PORT = int(os.getenv("BITWIG_REPLY_PORT", "9001"))

# BitwigStepPlugin läuft auf eigenem Port (getrennt von OscBridge 8001)
OSC_STEP_PORT       = int(os.getenv("BITWIG_STEP_PORT",       "8002"))
OSC_STEP_REPLY_PORT = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002"))


def _check_connection(timeout: float = 1.0) -> bool:
    """Prüft Verbindung zur BitwigAgentBridge via Ping/Pong auf Reply-Port 9001."""
    try:
        from src.agent.tools.song_tools import _check_bridge
        return _check_bridge(timeout=timeout)
    except Exception:
        return False


def _wait_osc_reply(address: str, timeout: float = 4.0) -> bool:
    """Wartet auf ein OSC-Reply von der BitwigAgentBridge auf dem Reply-Port.

    Gibt True zurück wenn das erwartete OSC-Paket innerhalb von `timeout` Sekunden
    eintrifft, False bei Timeout. Ignoriert Port-Konflikte (gibt dann True zurück
    damit der Executor nicht blockiert).
    """
    import socket as _socket
    import threading

    received = threading.Event()

    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    try:
        sock.bind(("", OSC_REPLY_PORT))
    except OSError:
        sock.close()
        return True  # Port belegt — anderer Listener aktiv, kein Block

    def _listen() -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(1024)
                # OSC-Adresse ist null-terminierter String am Anfang
                addr_end = data.find(b"\x00")
                if addr_end < 0:
                    continue
                osc_addr = data[:addr_end].decode("ascii", errors="ignore")
                if osc_addr == address:
                    received.set()
                    return
            except (_socket.timeout, OSError):
                break
            except Exception:
                break

    threading.Thread(target=_listen, daemon=True).start()
    try:
        return received.wait(timeout)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _osc(address: str, value=1, host: str = OSC_HOST, port: int = OSC_PORT):
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(host, port)
    client.send_message(address, value)


def _require_bridge() -> str | None:
    """Gibt Fehlermeldung zurück wenn BitwigAgentBridge nicht erreichbar."""
    if not _check_connection(timeout=1.5):
        return (
            "Fehler: OSC message not received — BitwigAgentBridge antwortet nicht.\n"
            "Prüfen:\n"
            "  1. Bitwig Studio läuft\n"
            "  2. BitwigAgentBridge Extension ist aktiv (Settings → Extensions)\n"
            "  3. Port 8001 ist frei (kein anderer Prozess)"
        )
    return None


_note_counts: dict[str, int] = {}  # "track:slot" → Noten pro Session

# ── Arranger ──────────────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_record_to_arrangement(length_seconds: float = 30.0) -> str:
    """Zeichnet die aktiven Scenes/Clips aus dem Clip Launcher in die Arranger-Timeline auf.

    Workflow:
      1. Wechselt zur Arrange-Ansicht
      2. Aktiviert Arrangement-Recording
      3. Startet Wiedergabe (Clip Launcher läuft parallel)
      4. Wartet length_seconds Sekunden
      5. Stoppt Recording

    Danach sind alle Clips als Arranger-Clips in der Timeline.

    Args:
        length_seconds: Aufnahmedauer in Sekunden (Standard: 30s)
    """
    if err := _require_bridge(): return err
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)

    client.send_message("/arrange/view", 1)
    time.sleep(0.3)
    client.send_message("/arrange/record/start", 1)
    time.sleep(length_seconds)
    client.send_message("/arrange/record/stop", 1)

    return f"Arrangement-Recording abgeschlossen ({length_seconds:.0f}s) — Clips in Timeline"


@mcp.tool()
def bitwig_arrange_view() -> str:
    """Wechselt zur Arranger-Ansicht (Timeline) in Bitwig."""
    if err := _require_bridge(): return err
    _osc("/arrange/view", 1)
    return "Arrange-Ansicht aktiviert"


# ── Transport ─────────────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_check_connection() -> str:
    """Prüft ob die BitwigAgentBridge erreichbar ist (Ping/Pong Test)."""
    if _check_connection(timeout=2.0):
        return "BitwigAgentBridge erreichbar ✓ (Port 8001)"
    return (
        "Fehler: OSC message not received — Bridge antwortet nicht.\n"
        "  1. Bitwig Studio starten\n"
        "  2. Settings → Extensions → BitwigAgentBridge aktivieren\n"
        "  3. Port 8001 prüfen: ss -tulpn | grep 8001"
    )


@mcp.tool()
def bitwig_play() -> str:
    """Startet die Wiedergabe in Bitwig Studio."""
    if err := _require_bridge(): return err
    _osc("/transport/play", 1)
    return "Wiedergabe gestartet"


@mcp.tool()
def bitwig_stop() -> str:
    """Stoppt die Wiedergabe in Bitwig Studio."""
    _osc("/transport/play", 0)
    return "Wiedergabe gestoppt"


@mcp.tool()
def bitwig_set_tempo(bpm: float) -> str:
    """Setzt das Tempo in Bitwig Studio.

    Args:
        bpm: Beats per Minute (z.B. 140.0 für Nu-Metal)
    """
    _osc("/transport/tempo", int(bpm))
    return f"Tempo auf {bpm} BPM gesetzt"


# ── Tracks ────────────────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_add_instrument_track() -> str:
    """Erstellt einen neuen Instrument-Track in Bitwig Studio."""
    if err := _require_bridge(): return err
    _osc("/track/add/instrument", 1)
    time.sleep(0.2)
    return "Instrument-Track erstellt"


@mcp.tool()
def bitwig_add_audio_track() -> str:
    """Erstellt einen neuen Audio-Track in Bitwig Studio."""
    _osc("/track/add/audio", 1)
    time.sleep(0.2)
    return "Audio-Track erstellt"


@mcp.tool()
def bitwig_add_effect_track() -> str:
    """Erstellt einen neuen Effect/Return-Track in Bitwig Studio.
    Effect-Tracks sind globale Send-Busse (z.B. Reverb, Delay).
    Tracks senden via /track/{n}/send/{m} an Effect-Track m (0-basiert).
    """
    if err := _require_bridge(): return err
    _osc("/track/add/effect", 1)
    time.sleep(0.3)
    return "Effect/Return-Track erstellt"


@mcp.tool()
def bitwig_set_send_level(track_index: int, send_index: int, level: float) -> str:
    """Setzt den Send-Pegel eines Tracks zu einem Effect/Return-Track.

    Args:
        track_index: Track-Nummer (1-basiert)
        send_index:  Index des Effect-Tracks (0-basiert, entspricht Reihenfolge der Effect-Tracks)
        level:       Send-Pegel 0.0 (kein Send) bis 1.0 (voller Send)
    """
    if err := _require_bridge(): return err
    level = max(0.0, min(1.0, float(level)))
    # Kurze Pause damit Bitwig den Track vollständig initialisiert hat
    time.sleep(0.8)
    _osc(f"/track/{track_index}/send/{send_index}", level)
    return f"Track {track_index} → Send {send_index} = {level:.2f}"


@mcp.tool()
def bitwig_add_group_track() -> str:
    """Erstellt einen neuen Group-Track in Bitwig Studio.
    Group-Tracks dienen als Container für mehrere Sub-Tracks (Drum Bus, Synth Bus etc.).
    """
    if err := _require_bridge(): return err
    _osc("/track/add/group", 1)
    time.sleep(0.3)
    return "Group-Track erstellt (falls Bitwig-Action verfügbar)"


@mcp.tool()
def bitwig_select_track(track_index: int) -> str:
    """Wählt einen Track aus (1-basiert).

    Args:
        track_index: Track-Nummer (1 = erster Track)
    """
    _osc(f"/track/{track_index}/select", 1)
    return f"Track {track_index} ausgewählt"


@mcp.tool()
def bitwig_set_track_volume(track_index: int, volume: float) -> str:
    """Setzt die Lautstärke eines Tracks.

    Args:
        track_index: Track-Nummer (1-basiert)
        volume: Lautstärke 0.0–1.0 (0.8 = 80%)
    """
    _osc(f"/track/{track_index}/volume", float(volume))
    return f"Track {track_index} Lautstärke: {volume:.0%}"


@mcp.tool()
def bitwig_pan_track(track_index: int, pan: float = 0.5) -> str:
    """Setzt das Panning eines Tracks.

    Args:
        track_index: Track-Nummer (1-basiert)
        pan: 0.0=links, 0.5=Mitte, 1.0=rechts
    """
    _osc(f"/track/{track_index}/pan", float(pan))
    pos = "links" if pan < 0.4 else "rechts" if pan > 0.6 else "Mitte"
    return f"Track {track_index} Pan: {pos} ({pan:.0%})"


@mcp.tool()
def bitwig_solo_track(track_index: int, solo: bool = True) -> str:
    """Soloed oder un-soloed einen Track.

    Args:
        track_index: Track-Nummer (1-basiert)
        solo: True = Solo an, False = Solo aus
    """
    _osc(f"/track/{track_index}/solo", 1 if solo else 0)
    state = "gesolo'd" if solo else "Solo aus"
    return f"Track {track_index} {state}"


@mcp.tool()
def bitwig_mute_track(track_index: int, mute: bool = True) -> str:
    """Muted oder unmuted einen Track.

    Args:
        track_index: Track-Nummer
        mute: True = muten, False = unmuten
    """
    _osc(f"/track/{track_index}/mute", 1 if mute else 0)
    return f"Track {track_index} {'gemuted' if mute else 'unmuted'}"


# ── Instrumente laden ─────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_load_instrument(
    track_index: int,
    instrument_name: str,
    collection: str = "",
) -> str:
    """Lädt ein Instrument auf einen Track über den Bitwig Browser.

    Strategie:
      1. Kategorie-Spalte (linke Spalte) nach Name durchsuchen → isSelected().set(true)
      2. Optional: Smart-Collection vorfiltern (collection-Parameter)
      3. Fallback: Position im Ergebnis-Katalog

    Args:
        track_index:     Track-Nummer (1-basiert)
        instrument_name: Bitwig-Device-Name (z.B. 'FM-4', 'Organ', 'Polysynth')
        collection:      Optionale Smart-Collection als Vorfilter (z.B. 'BitwigAgent')
    """
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)

    # 1. Track auswählen (CursorTrack + CursorDevice folgen)
    client.send_message(f"/track/{track_index}/select", 1)
    time.sleep(0.3)

    # 2. Collection-Filter setzen (optional)
    if collection:
        client.send_message("/browser/collection", collection)
        time.sleep(0.1)

    # 3. Prüfen ob Built-in UUID bekannt → bereits in Java erledigt durch /browser/device/load
    #    Fallback: Device-Browser mit commitSelectedResult() (zuverlässiger als PopupBrowser)
    client.send_message("/browser/device/load", instrument_name)
    # Kurz warten — wenn UUID bekannt, ist es sofort fertig
    time.sleep(0.5)

    # Prüfe ob es ein Built-in Device ist (kein weiterer Browser-Schritt nötig)
    builtin = {
        "organ", "fm-4", "phase-4", "polysynth", "polymer", "drum machine",
        "sampler", "chain", "arpeggiator", "chorus", "compressor", "delay",
        "distortion", "eq-5", "flanger", "limiter", "note filter",
        "note length", "note transpose",
    }
    if instrument_name.lower().strip() in builtin:
        return f"'{instrument_name}' auf Track {track_index} geladen (UUID)"

    # 4. Fallback: Device-Browser für VST / Surge XT / Presets
    client.send_message("/device/browser/start", 1)
    time.sleep(2.5)  # Browser öffnet + Ergebnisse laden

    client.send_message("/device/browser/navigate/name", instrument_name)
    time.sleep(1.0)  # Cursor auf Ziel

    client.send_message("/device/browser/commit", 1)
    time.sleep(1.0)  # Device wird eingefügt

    return f"'{instrument_name}' auf Track {track_index} geladen"


@mcp.tool()
def bitwig_append_effect(
    track_index: int,
    effect_name: str,
) -> str:
    """Fügt einen Effekt ans ENDE der Device-Chain eines Tracks an.

    Benutze dieses Tool für FX auf Instrument-Tracks (Reverb, Delay-2, Chorus etc.)
    — NICHT bitwig_load_instrument, das fügt vor dem Cursor ein und kann Reihenfolge
    durcheinander bringen.

    Args:
        track_index: Track-Nummer (1-basiert)
        effect_name: Bitwig-Device-Name (z.B. 'Reverb', 'Delay-2', 'Chorus', 'Compressor')
    """
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    client.send_message(f"/track/{track_index}/select", 1)
    time.sleep(0.3)
    client.send_message("/browser/device/append", effect_name)
    time.sleep(0.5)
    return f"'{effect_name}' ans Ende der Chain von Track {track_index} angehängt"


@mcp.tool()
def bitwig_browser_commit() -> str:
    """Bestätigt die aktuelle Browser-Auswahl in Bitwig."""
    _osc("/browser/commit", 1)
    return "Browser-Auswahl bestätigt"


@mcp.tool()
def bitwig_browser_next(steps: int = 1) -> str:
    """Navigiert im Bitwig Browser vorwärts.

    Args:
        steps: Anzahl der Schritte vorwärts
    """
    for _ in range(steps):
        _osc("/browser/next", 1)
        time.sleep(0.08)
    return f"Browser {steps} Schritt(e) vorwärts"


# ── Parameter setzen ──────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_set_parameter(param_index: int, value: float) -> str:
    """Setzt einen Device-Parameter des ausgewählten Instruments.

    Args:
        param_index: Parameter-Index 1–8
        value: Wert 0.0–1.0
    """
    _osc(f"/device/param/{param_index}/value", float(value))
    return f"Parameter {param_index} = {value:.2f}"


@mcp.tool()
def bitwig_set_named_parameter(param_name: str, value: float) -> str:
    """Setzt einen Device-Parameter nach Namen.

    Beispiele: 'Tune', 'Drive', 'Cutoff', 'Attack', 'Decay'

    Args:
        param_name: Name des Parameters (Groß-/Kleinschreibung egal)
        value: Wert 0.0–1.0
    """
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    client.send_message("/device/param/named", [param_name, float(value)])
    return f"Parameter '{param_name}' = {value:.2f}"


# ── EQ ────────────────────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_eq_band(band: int, freq_hz: float = 0, gain_db: float = 0) -> str:
    """Stellt ein EQ-5 Band ein.

    Args:
        band: Band-Nummer 1–8
        freq_hz: Frequenz in Hz (0 = nicht ändern)
        gain_db: Gain in dB ±24 (0 = nicht ändern)
    """
    import math
    if freq_hz > 0:
        norm = math.log10(max(freq_hz, 20) / 20) / math.log10(20000 / 20)
        _osc(f"/eq/freq/{band}", round(min(1.0, max(0.0, norm)), 4))
    if gain_db != 0:
        norm = (gain_db + 24) / 48
        _osc(f"/eq/gain/{band}", round(min(1.0, max(0.0, norm)), 4))
    parts = []
    if freq_hz > 0: parts.append(f"{freq_hz:.0f}Hz")
    if gain_db != 0: parts.append(f"{gain_db:+.1f}dB")
    return f"EQ Band {band}: {', '.join(parts)}"


# ── Clip & Note Programming ───────────────────────────────────────────────────

@mcp.tool()
def bitwig_create_clip(track_index: int, slot: int = 0, length_beats: float = 8.0) -> str:
    """Erstellt einen leeren Clip im Clip-Launcher eines Tracks.

    Args:
        track_index:  Track-Nummer (1-basiert)
        slot:         Clip-Slot Index (0-basiert)
        length_beats: Clip-Länge in Beats (8 = 2 Takte bei 4/4)
    """
    from pythonosc import udp_client
    _osc(f"/track/{track_index}/select", 1)
    time.sleep(0.15)
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    client.send_message("/clip/create", [float(slot), float(length_beats)])
    time.sleep(0.3)
    return f"Clip erstellt: Track {track_index}, Slot {slot}, {length_beats} Beats"


@mcp.tool()
def bitwig_launch_clip(track_index: int, slot: int = 0) -> str:
    """Startet einen Clip-Slot auf einem Track.

    Args:
        track_index: Track-Nummer (1-basiert)
        slot:        Clip-Slot Index (0-basiert)
    """
    _osc(f"/track/{track_index}/select", 1)
    time.sleep(0.05)
    _osc("/clip/launch", slot)
    return f"Clip gestartet: Track {track_index}, Slot {slot}"


@mcp.tool()
def bitwig_set_step_size(beats: float = 0.25) -> str:
    """Setzt die Schrittauflösung des aktiven Clips.

    Args:
        beats: Schrittgröße in Beats — 0.25=1/16, 0.5=1/8, 1.0=Viertelnote
    """
    labels = {0.125: "1/32", 0.25: "1/16", 0.5: "1/8", 1.0: "1/4", 2.0: "1/2"}
    label = labels.get(beats, f"{beats}b")
    _osc("/clip/step_size", float(beats))
    return f"Step-Größe: {label}"


@mcp.tool()
def bitwig_clear_clip(track_index: int) -> str:
    """Löscht alle Noten aus dem aktiven Clip eines Tracks.

    Args:
        track_index: Track-Nummer (1-basiert)
    """
    _osc(f"/track/{track_index}/select", 1)
    time.sleep(0.1)
    _osc("/clip/clear", 1)
    time.sleep(0.5)
    return f"Clip geleert: Track {track_index}"


@mcp.tool()
def bitwig_add_note(step: int, pitch: int, velocity: float = 0.8, duration: float = 0.25) -> str:
    """Fügt eine einzelne MIDI-Note in den aktiven Clip ein.

    MIDI-Referenz: 36=C2/Kick, 38=D2/Snare, 42=F#2/HiHat, 48=C3, 60=C4
    Schritte bei 1/16: 16 pro Takt — Step 0=Zählzeit 1, Step 4=Zählzeit 2 usw.

    Args:
        step:     Schritt-Index (0-basiert)
        pitch:    MIDI-Notennummer (0–127)
        velocity: Anschlagsstärke 0.0–1.0
        duration: Dauer in Beats (0.25=1/16, 0.5=1/8, 1.0=Viertelnote)
    """
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    client.send_message("/clip/note", [step, pitch, float(velocity), float(duration)])
    time.sleep(0.02)
    return f"Note: step={step} pitch={pitch} vel={velocity:.0%} dur={duration}b"


@mcp.tool()
def bitwig_note_pattern(track_index: int, notes_json: str, slot: int = 0, length_beats: float = 8.0) -> str:
    """Programmiert ein vollständiges Notenmuster in einen Clip.

    notes_json Format:
        [{"step": 0, "pitch": 36, "vel": 0.9, "dur": 0.25}, ...]

    Args:
        track_index:  Track-Nummer (1-basiert)
        notes_json:   JSON-Array mit Noten-Objekten
        slot:         Clip-Slot (0-basiert)
        length_beats: Clip-Länge in Beats (Standard: 8 = 2 Takte)
    """
    if err := _require_bridge(): return err
    import json
    notes = json.loads(notes_json)
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)

    _osc(f"/track/{track_index}/select", 1)
    time.sleep(0.5)   # länger warten — CursorClip muss folgen
    client.send_message("/clip/create", [float(slot), float(length_beats)])
    time.sleep(0.8)   # Clip muss bereit sein bevor Noten geschrieben werden
    client.send_message("/clip/step_size", 0.25)
    time.sleep(0.1)
    client.send_message("/clip/clear", 1)  # vorherige Noten löschen
    time.sleep(0.2)

    for n in notes:
        # /clip/note/beat: Beat-Position direkt übergeben — keine Rundungsfehler
        client.send_message("/clip/note/beat", [
            float(n["step"]),
            float(n["pitch"]),   # als Float senden — argFloat(msg,1) schlägt bei Int fehl
            float(n.get("vel", 0.8)),
            float(n.get("dur", 0.25)),
        ])
        time.sleep(0.03)

    return f"Pattern: Track {track_index}, Slot {slot}, {len(notes)} Noten, {length_beats} Beats"


@mcp.tool()
def bitwig_param_sequence(param_name: str, values_json: str, delay_ms: int = 100) -> str:
    """Sequenziert einen Device-Parameter für Bewegung und Variation.

    values_json: JSON-Array von Werten, z.B. "[0.2, 0.5, 0.8, 0.5, 0.3]"
    Jeder Wert wird mit delay_ms Millisekunden Abstand gesendet.

    Args:
        param_name:  Parametername (z.B. 'Cutoff', 'Drive', 'Attack')
        values_json: JSON-Array mit Werten 0.0–1.0
        delay_ms:    Millisekunden zwischen Schritten (50–2000)
    """
    import json
    vals = json.loads(values_json)
    delay_s = max(0.05, min(2.0, delay_ms / 1000.0))
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    for v in vals:
        client.send_message("/device/param/named", [param_name, float(v)])
        time.sleep(delay_s)
    return f"Parameter '{param_name}': {len(vals)} Werte @ {delay_ms}ms"


@mcp.tool()
def bitwig_nu_metal_drums(kick_track: int, snare_track: int, hihat_track: int = 0, bars: int = 2) -> str:
    """Programmiert ein Nu-Metal Schlagzeug-Pattern (1/16-Raster).

    Pattern (2 Takte, 4/4):
    - Kick:   synkopiert mit Doppelschlägen
    - Snare:  Zählzeiten 2 und 4
    - HiHat:  Achtelnoten mit Akzenten auf den Zählzeiten

    MIDI: 36=Kick(C2), 38=Snare(D2), 42=HiHat(F#2)

    Args:
        kick_track:  Track für E-Kick (1-basiert)
        snare_track: Track für E-Snare (1-basiert)
        hihat_track: Track für E-HiHat (0 = weglassen)
        bars:        Anzahl Takte (1 oder 2)
    """
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    sbar = 16
    total = bars * sbar
    length = bars * 4.0

    # Kick: synkopiert — Betonung + Upbeats + gelegentliche Doppelhits
    kick = [0, 3, 6, 8, 10, 14]
    if bars >= 2:
        kick += [s + sbar for s in [0, 2, 6, 8, 11, 13, 14]]

    # Snare: Zählzeiten 2 + 4
    snare = []
    for b in range(bars):
        snare += [b * sbar + 4, b * sbar + 12]

    # HiHat: Achtelnoten (jeden 2. Step)
    hihat = list(range(0, total, 2))

    def program(track_idx, steps, pitch, vel_main, vel_off):
        _osc(f"/track/{track_idx}/select", 1)
        time.sleep(0.15)
        client.send_message("/clip/create", [0, length])
        time.sleep(0.4)
        client.send_message("/clip/step_size", 0.25)
        time.sleep(0.05)
        for s in steps:
            vel = vel_main if s % sbar in (0, 8) else vel_off
            client.send_message("/clip/note", [s, pitch, round(vel, 2), 0.2])
            time.sleep(0.02)

    program(kick_track,  kick,  36, 0.90, 0.78)
    program(snare_track, snare, 38, 0.95, 0.90)
    if hihat_track > 0:
        program(hihat_track, hihat, 42, 0.55, 0.45)

    summary = (f"Nu-Metal Drums: "
               f"Kick={kick_track}({len(kick)} Hits), "
               f"Snare={snare_track}({len(snare)} Hits)")
    if hihat_track > 0:
        summary += f", HiHat={hihat_track}({len(hihat)} Hits)"
    return summary


# ── Compound: Setup aus Genre-Wissen ─────────────────────────────────────────

@mcp.tool()
def bitwig_setup_genre(genre: str, bpm: float = 120.0) -> str:
    """Erstellt automatisch ein Genre-Setup in Bitwig.

    Fragt Neo4j nach Genre-spezifischen Devices und erstellt
    alle nötigen Tracks mit dem richtigen Tempo.

    Args:
        genre: Genre-Name (z.B. 'Dubstep', 'Nu-Metal', 'Techno', 'House')
        bpm: Tempo in BPM
    """
    # Tempo setzen
    _osc("/tempo/raw", float(bpm))

    # Genre-Devices aus Neo4j
    try:
        from src.knowledge.neo4j_graph import session
        with session() as s:
            devices = s.run("""
                MATCH (g:Genre)-[r:USES]->(d:Device)
                WHERE toLower(g.name) CONTAINS toLower($genre)
                RETURN d.name AS name, r.role AS role, r.weight AS weight
                ORDER BY r.weight DESC LIMIT 8
            """, genre=genre).data()
    except Exception:
        devices = []

    if not devices:
        return f"Genre '{genre}' nicht in DB — manuelle Konfiguration nötig"

    # Tracks erstellen
    track_info = []
    for dev in devices[:6]:
        _osc("/track/add/instrument", 1)
        time.sleep(0.25)
        track_info.append(f"  Track → {dev['name']} ({dev['role']})")

    return (
        f"Setup für '{genre}' ({bpm} BPM):\n" +
        "\n".join(track_info) +
        f"\n\nInstrumente jetzt per Browser zuweisen:\n" +
        "\n".join(f"  /browser/device/load {d['name']}" for d in devices[:6])
    )


# ── Browser-Scan & DB-Update ──────────────────────────────────────────────────

# Linux-native Pfad (Java-Extension schreibt per Default in ~/bitwig_catalog.json)
_CATALOG_PATH = os.path.expanduser("~/bitwig_catalog.json")


@mcp.tool()
def bitwig_scan_browser() -> str:
    """Scannt den Bitwig Browser-Katalog und gibt alle gefundenen Device-Namen zurück.

    Öffnet den Device-Browser in Bitwig, wartet 3s auf Katalog-Aufbau,
    speichert als JSON nach C:\\Users\\Public\\bitwig_catalog.json
    (lesbar aus WSL als /mnt/c/Users/Public/bitwig_catalog.json).

    Voraussetzung: Bitwig läuft + BitwigAgentBridge aktiv.
    """
    import json, os
    from pythonosc import udp_client
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)

    client.send_message("/browser/device", 1)
    time.sleep(3.0)  # Katalog-Aufbau abwarten

    client.send_message("/browser/catalog/save", _CATALOG_PATH)
    time.sleep(0.8)

    _osc("/browser/cancel", 1)
    time.sleep(0.2)

    if not os.path.exists(_CATALOG_PATH):
        return f"Katalog nicht gefunden: {_CATALOG_PATH}\nBitwig + Bridge aktiv?"

    with open(_CATALOG_PATH) as f:
        catalog = json.load(f)

    names = sorted(e["name"] for e in catalog)
    lines = "\n".join(f"  {i+1:3d}. {n}" for i, n in enumerate(names))
    return f"Browser-Katalog ({len(names)} Einträge):\n{lines}"


@mcp.tool()
def bitwig_search_catalog(search_term: str) -> str:
    """Sucht im zuletzt gespeicherten Browser-Katalog nach Devices.

    bitwig_scan_browser() muss vorher einmal ausgeführt worden sein.

    Args:
        search_term: Suchbegriff (Groß-/Kleinschreibung egal)
    """
    import json, os
    if not os.path.exists(_CATALOG_PATH):
        return "Kein Katalog vorhanden — bitte zuerst bitwig_scan_browser() ausführen"

    with open(_CATALOG_PATH) as f:
        catalog = json.load(f)

    term = search_term.lower()
    hits = sorted(e["name"] for e in catalog if term in e["name"].lower())

    if not hits:
        return f"Keine Treffer für '{search_term}'"
    lines = "\n".join(f"  - {n}" for n in hits)
    return f"Treffer für '{search_term}' ({len(hits)}):\n{lines}"


@mcp.tool()
def bitwig_upsert_device(
    name: str,
    device_type: str = "instrument",
    category: str = "other",
    description: str = "",
    browser_path: str = "",
) -> str:
    """Fügt ein Device in die Neo4j Wissensdatenbank ein oder aktualisiert es.

    Args:
        name:         Exakter Browser-Name aus Bitwig (z.B. 'E-Kick', 'Distortion')
        device_type:  'instrument', 'effect', 'midi_effect'
        category:     z.B. 'drum_synth', 'dynamics', 'saturation', 'synthesizer'
        description:  Kurzbeschreibung
        browser_path: Browser-Pfad (z.B. 'Instruments > Drums > E-Kick')
    """
    from src.knowledge.neo4j_graph import session
    with session() as s:
        s.run("""
            MERGE (d:Device {name: $name})
            SET d.type=$type, d.category=$category,
                d.description=$description, d.browser_path=$browser_path
        """, name=name, type=device_type, category=category,
             description=description, browser_path=browser_path)
    return f"Device '{name}' gespeichert (type={device_type}, category={category})"


@mcp.tool()
def bitwig_upsert_genre(
    genre: str,
    bpm_min: int = 100,
    bpm_max: int = 160,
    key_mode: str = "minor",
    description: str = "",
) -> str:
    """Fügt ein Genre in die Neo4j DB ein oder aktualisiert es.

    Args:
        genre:       Genre-Name (z.B. 'Nu-Metal', 'Techno')
        bpm_min:     Minimales Tempo
        bpm_max:     Maximales Tempo
        key_mode:    'minor', 'major', 'chromatic'
        description: Kurzbeschreibung
    """
    from src.knowledge.neo4j_graph import session
    with session() as s:
        s.run("""
            MERGE (g:Genre {name: $name})
            SET g.bpm_min=$bpm_min, g.bpm_max=$bpm_max,
                g.key_mode=$key_mode, g.description=$description
        """, name=genre, bpm_min=bpm_min, bpm_max=bpm_max,
             key_mode=key_mode, description=description)
    return f"Genre '{genre}' gespeichert"


@mcp.tool()
def bitwig_link_genre_device(
    genre: str,
    device: str,
    role: str = "instrument",
    weight: float = 0.8,
) -> str:
    """Verknüpft ein Genre mit einem Device in der DB (Genre -[USES]-> Device).

    Args:
        genre:   Genre-Name (muss in DB existieren)
        device:  Device-Name (muss in DB existieren)
        role:    z.B. 'drums', 'bass', 'guitar_fx', 'dynamics', 'bass_synth'
        weight:  Wichtigkeit 0.0–1.0
    """
    from src.knowledge.neo4j_graph import session
    with session() as s:
        row = s.run("""
            MATCH (g:Genre {name: $genre}), (d:Device {name: $device})
            MERGE (g)-[r:USES {role: $role}]->(d)
            SET r.weight = $weight
            RETURN g.name AS g, d.name AS d
        """, genre=genre, device=device, role=role, weight=weight).single()
    if row:
        return f"'{genre}' --[{role}, w={weight}]--> '{device}'"
    return f"FEHLER: '{genre}' oder '{device}' nicht in DB — zuerst bitwig_upsert_device/genre aufrufen"


@mcp.tool()
def bitwig_query_genre_devices(genre: str) -> str:
    """Zeigt alle Devices für ein Genre aus der Neo4j DB.

    Args:
        genre: Genre-Name oder Teilstring (Groß-/Kleinschreibung egal)
    """
    from src.knowledge.neo4j_graph import session
    with session() as s:
        rows = s.run("""
            MATCH (g:Genre)-[r:USES]->(d:Device)
            WHERE toLower(g.name) CONTAINS toLower($genre)
            RETURN g.name AS genre, d.name AS device, r.role AS role,
                   r.weight AS weight, d.type AS type, d.browser_path AS path
            ORDER BY r.weight DESC
        """, genre=genre).data()

    if not rows:
        return f"Keine Devices für '{genre}' in DB"

    lines = []
    for r in rows:
        lines.append(f"  {r['device']:22s}  role={r['role']:12s}  w={r['weight']:.2f}  [{r['type']}]")
    return f"Devices für '{rows[0]['genre']}' ({len(rows)}):\n" + "\n".join(lines)


@mcp.tool()
def bitwig_ingest_catalog_to_db(filter_term: str = "") -> str:
    """Liest den zuletzt gespeicherten Browser-Katalog und ingested alle Devices in Neo4j.

    Kategorisiert Devices automatisch anhand der Namen.
    Optional: nur Devices die filter_term enthalten.

    Args:
        filter_term: Nur Devices mit diesem Begriff ingesten (leer = alle)
    """
    import json, os
    if not os.path.exists(_CATALOG_PATH):
        return "Kein Katalog vorhanden — bitte zuerst bitwig_scan_browser() ausführen"

    with open(_CATALOG_PATH) as f:
        catalog = json.load(f)

    if filter_term:
        catalog = [e for e in catalog if filter_term.lower() in e["name"].lower()]

    DRUM_KEYS = ("e-kick", "e-snare", "e-hi", "e-tom", "e-clap", "e-cowbell")
    SYNTH_KEYS = ("polymer", "phase-4", "fm-4", "polysynth", "sampler", "drum machine",
                  "operators", "instrument layer")
    FX_KEYS    = ("distortion", "saturator", "compressor", "eq-5", "eq-2", "delay",
                  "reverb", "ladder filter", "transient control", "limiter", "flanger",
                  "freq shifter", "pitch shifter", "amp designer", "cabinet", "bit-8",
                  "ring mod", "gate", "comb filter", "rotary", "chorus")

    from src.knowledge.neo4j_graph import session
    ingested = []
    with session() as s:
        for entry in catalog:
            name = entry["name"]
            key  = name.lower()

            if any(k in key for k in DRUM_KEYS):
                dtype, cat = "instrument", "drum_synth"
                bpath = f"Instruments > Drums > {name}"
            elif any(k in key for k in SYNTH_KEYS):
                dtype, cat = "instrument", "synthesizer"
                bpath = f"Instruments > Synthesizers > {name}"
            elif any(k in key for k in FX_KEYS):
                dtype, cat = "effect", "audio_fx"
                bpath = f"Devices > Audio FX > {name}"
            else:
                dtype, cat = "instrument", "other"
                bpath = f"Instruments > {name}"

            s.run("""
                MERGE (d:Device {name: $name})
                SET d.type=$type, d.category=$category, d.browser_path=$bpath
            """, name=name, type=dtype, category=cat, bpath=bpath)
            ingested.append(f"  {name:30s} [{dtype}/{cat}]")

    result = f"Ingested {len(ingested)} Devices:\n" + "\n".join(ingested)
    return result


# ── DAWproject öffnen ─────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_open_dawproject(path: str) -> str:
    """Hinweis zum Öffnen eines DAWprojects in Bitwig.

    Da Bitwig keine direkte 'Open File' OSC API hat,
    wird der Windows-Pfad ausgegeben.

    Args:
        path: WSL-Pfad zur .dawproject Datei
    """
    win_path = path.replace("/mnt/c/", "C:\\\\").replace("/", "\\\\")
    wsl_path = path.replace("/mnt/", "\\\\\\\\wsl.localhost\\\\CachyOS_v4\\\\")
    return (
        f"DAWproject öffnen in Bitwig:\n"
        f"Datei → Öffnen → {path}\n\n"
        f"Windows Explorer:\n{wsl_path if path.startswith('/home') else win_path}"
    )


@mcp.tool()
def bitwig_song_from_chords(
    genre: str = "pop",
    section: str = "verse_1",
    beats_per_chord: float = 2.0,
    bass_track: int = 2,
    chord_track: int = 3,
    slot: int = 0,
) -> str:
    """Holt eine echte Akkordprogression aus der KB (Chordonomicon) und schreibt
    sie direkt als Bass- und Chord-Pattern in Bitwig.

    Workflow:
        1. Neo4j → Chordonomicon-Eintrag für das Genre
        2. Akkord-Parser → MIDI-Noten (Bass + Voicings)
        3. OSC → bitwig_note_pattern auf die gewählten Tracks

    Args:
        genre:           Musik-Genre ("pop", "rock", "jazz" ...)
        section:         Sektion aus dem Song ("verse_1", "chorus_1", ...)
        beats_per_chord: Beats pro Akkord (2.0 = 8 Akkorde in 2 Takten)
        bass_track:      Track-Nummer für Bass (1-basiert)
        chord_track:     Track-Nummer für Chords (1-basiert)
        slot:            Clip-Slot (0-basiert)
    """
    import json
    import os
    from src.audio.chord_to_bitwig import query_chordonomicon, progression_to_pattern
    from pythonosc import udp_client

    # ── 1. Progression aus KB laden ───────────────────────────────────────────
    results = query_chordonomicon(genre=genre, n=1)

    if not results:
        return f"Keine Progression für Genre '{genre}' in KB gefunden."

    parsed   = results[0]
    sections = parsed["sections"]

    # Sektion wählen — fallback auf erste verfügbare
    chords = sections.get(section) or next(iter(sections.values()), [])
    if not chords:
        return f"Keine Akkorde in Sektion '{section}' gefunden. Verfügbar: {list(sections.keys())}"

    # Zu lang? Max 8 Akkorde pro Clip
    chords = chords[:8]

    # ── 2. Pattern erzeugen ───────────────────────────────────────────────────
    pattern = progression_to_pattern(chords, beats_per_chord=beats_per_chord)
    length  = pattern["length_beats"]

    # ── 3. In Bitwig schreiben ────────────────────────────────────────────────
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    step_size = 0.25

    def write_pattern(track_idx: int, notes: list[dict]) -> None:
        _osc(f"/track/{track_idx}/select", 1)
        time.sleep(0.15)
        client.send_message("/clip/create", [float(slot), float(length)])
        time.sleep(0.4)
        client.send_message("/clip/step_size", step_size)
        time.sleep(0.05)
        for n in notes:
            step_idx = int(round(float(n["step"]) / step_size))
            client.send_message("/clip/note", [
                step_idx,
                float(n["pitch"]),   # Float statt Int
                float(n.get("vel", 0.8)),
                float(n.get("dur", 0.25)),
            ])
            time.sleep(0.02)

    write_pattern(bass_track,  pattern["bass"])
    write_pattern(chord_track, pattern["chords"])

    chord_str = " → ".join(chords)
    return (
        f"Chordonomicon ({parsed['genre']}, {int(parsed['decade'])}er):\n"
        f"  Progression: {chord_str}\n"
        f"  Sektion: {section} | {len(chords)} Akkorde × {beats_per_chord} Beats = {length} Beats\n"
        f"  Bass:   {len(pattern['bass'])} Noten → Track {bass_track}, Slot {slot}\n"
        f"  Chords: {len(pattern['chords'])} Noten → Track {chord_track}, Slot {slot}"
    )


@mcp.tool()
def bitwig_launch_scene(slot: int, bpm: float = 0.0) -> str:
    """Startet alle Clips in einer Scene (Spalte) gleichzeitig.
    Optional: Tempo setzen vor dem Launch.

    Args:
        slot: Scene-Nummer (0-basiert, entspricht Clip-Slot)
        bpm:  Tempo in BPM (0 = nicht ändern)
    """
    if bpm > 0:
        _osc("/transport/tempo", float(bpm))
        time.sleep(0.05)
    _osc(f"/scene/{slot + 1}/launch", 1)
    tempo_info = f" @ {bpm} BPM" if bpm > 0 else ""
    return f"Scene {slot} gestartet{tempo_info}"


if __name__ == "__main__":
    print("Bitwig MCP Server startet...")
    print(f"OSC → {OSC_HOST}:{OSC_PORT} (BitwigAgentBridge)")
    mcp.run(transport="stdio")

# ── Launchpad MK2 ─────────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_launchpad_map(pad_note: int, action: str) -> str:
    """Weist einem Launchpad-Pad eine Bitwig-Aktion zu und setzt die LED-Farbe.

    Pad-Noten (Launchpad MK2 Session-Modus):
      Untere Reihe: 11–18  |  Zweite Reihe: 21–28  |  Dritte Reihe: 31–38
      Vierte Reihe: 41–48  |  Fünfte Reihe: 51–58  |  Sechste Reihe: 61–68
      Siebte Reihe: 71–78  |  Oberste Reihe: 81–88
      Rechte Buttons: 19, 29, 39, 49, 59, 69, 79, 89

    Verfügbare Aktionen:
      play_stop   — Transport Play/Stop umschalten (grüne LED)
      stop        — Transport Stop (orange)
      record      — Aufnahme starten (rote LED)
      undo        — Letzten Schritt rückgängig (gelbe LED)
      loop_toggle — Loop an/aus (lila LED)
      mute_toggle — Aktuellen Track muten (bernstein LED)
      next_track  — Nächsten Track auswählen (cyan LED)
      prev_track  — Vorherigen Track auswählen (blaue LED)

    Args:
        pad_note: MIDI-Note des Pads (z.B. 11 = unten links)
        action:   Aktion aus der Liste oben
    """
    if err := _require_bridge(): return err
    _osc("/launchpad/map", [int(pad_note), str(action)])
    return f"Pad {pad_note} → {action} (LED aktiv)"


@mcp.tool()
def bitwig_launchpad_led(pad_note: int, r: int, g: int, b: int) -> str:
    """Setzt die LED-Farbe eines Launchpad-Pads direkt (ohne Aktion zuzuweisen).

    Args:
        pad_note: MIDI-Note des Pads
        r:        Rot-Wert 0–63
        g:        Grün-Wert 0–63
        b:        Blau-Wert 0–63
    """
    if err := _require_bridge(): return err
    r = max(0, min(63, int(r)))
    g = max(0, min(63, int(g)))
    b = max(0, min(63, int(b)))
    _osc("/launchpad/led", [int(pad_note), r, g, b])
    return f"Pad {pad_note} LED = ({r},{g},{b})"


@mcp.tool()
def bitwig_launchpad_clear() -> str:
    """Löscht alle Launchpad-Pad-Mappings und schaltet alle LEDs aus."""
    if err := _require_bridge(): return err
    _osc("/launchpad/clear", 1)
    return "Alle Launchpad-Mappings gelöscht, LEDs aus"


# ── Note-Counter ──────────────────────────────────────────────────────────────

@mcp.tool()
def bitwig_get_note_counts() -> str:
    """Gibt die Anzahl der bisher geschriebenen Noten pro Track zurück.

    Zählt alle Noten die via bitwig_note_pattern oder bitwig_add_note
    in dieser Session geschrieben wurden.
    """
    if not _note_counts:
        return "Noch keine Noten in dieser Session geschrieben."
    lines = []
    total = 0
    for key in sorted(_note_counts):
        track, slot = key.split(":")
        count = _note_counts[key]
        total += count
        lines.append(f"  Track {track} Slot {slot}: {count} Noten")
    lines.append(f"  ──────────────────────")
    lines.append(f"  TOTAL: {total} Noten")
    return "\n".join(lines)


# ── execute_result — Thin Wrapper um src/bitwig_executor.py ──────────────────
# Logik lebt in src/bitwig_executor.py — hier nur MCP-Dekoratoren.

from src.bitwig_executor import (
    execute_setup  as _exec_setup,
    compose_notes  as _compose_notes,
    execute_result as _exec_result,
    _SETUP_TYPES,
    _NOTE_TYPES,
    _exec_step_and_wait,
)


@mcp.tool()
def execute_setup(result: dict) -> str:
    """Phase 1: Tracks, Instrumente, FX, Tempo anlegen. Keine Noten.

    Nach execute_setup: get_bitwig_track_state aufrufen, dann pro Track compose_notes.
    """
    return _exec_setup(result)


@mcp.tool()
def compose_notes(result: dict) -> str:
    """Phase 2: Noten für EINEN Track schreiben. Pro Instrument ein separater Call.

    result enthält: track, all_tracks, target (bpm/genre/key/chord_progression), steps.
    Musikalische Reihenfolge: Kick → Snare → Hat → Bass → Chords → Lead (letzter + play).
    """
    return _compose_notes(result)


@mcp.tool()
def execute_result(result: dict) -> str:
    """Rückwärtskompatibel: Setup + Noten in einem Call.

    Für neuen Code execute_setup() + compose_notes() pro Track verwenden.
    """
    return _exec_result(result)
